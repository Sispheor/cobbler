"""
Cobbler uses Cheetah templates for lots of stuff, but there's
some additional magic around that to deal with snippets/etc.
(And it's not spelled wrong!)

Copyright 2008-2009, Red Hat, Inc and Others
Michael DeHaan <michael.dehaan AT gmail>

This program is free software; you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation; either version 2 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program; if not, write to the Free Software
Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA
02110-1301  USA
"""

import functools
import os
import os.path
import pprint
import re
from typing import Optional, Union, TextIO

import Cheetah

from cobbler import clogger, utils
from cobbler.cexceptions import CX
from cobbler.cobbler_collections.manager import CollectionManager
from cobbler.template_api import CobblerTemplate

try:
    import jinja2

    jinja2_available = True
except ModuleNotFoundError:
    # FIXME: log a message here
    jinja2_available = False
    pass

CHEETAH_MACROS_FILE = '/etc/cobbler/cheetah_macros'


class Templar:
    """
    Wrapper to encapsulate all logic of Cheetah vs. Jinja2. This also enables us to remove and add templating as desired
    via our self-defined API in this class.
    """

    def __init__(self, collection_mgr, logger=None):
        """
        Constructor

        :param collection_mgr: The main collection manager instance which is used by the current running server.
        :param logger: The logger which audits the actions of the object instance.
        """

        self.collection_mgr = None
        self.settings = None
        if collection_mgr:
            self.collection_mgr = collection_mgr
            self.settings = collection_mgr.settings()

        self.last_errors = []

        if logger is None:
            logger = clogger.Logger()
        self.logger = logger

    def check_for_invalid_imports(self, data: str):
        """
        Ensure that Cheetah code is not importing Python modules that may allow for advanced privileges by ensuring we
        whitelist the imports that we allow.

        :param data: The Cheetah code to check.
        """
        lines = data.split("\n")
        for line in lines:
            if line.find("#import") != -1:
                rest = line.replace("#import", "").replace(" ", "").strip()
                if self.settings and rest not in self.settings.cheetah_import_whitelist:
                    raise CX("potentially insecure import in template: %s" % rest)

    def render(self, data_input: Union[TextIO, str], search_table: dict, out_path: Optional[str],
               template_type="default") -> str:
        """
        Render data_input back into a file.

        :param data_input: is either a str or a TextIO object.
        :param search_table: is a dict of metadata keys and values.
        :param out_path: Optional parameter which (if present), represents the target path to write the result into.
        :param template_type: May currently be "cheetah" or "jinja2". "default" looks in the settings.
        :return: The rendered template.
        """

        if not isinstance(data_input, str):
            raw_data = data_input.read()
        else:
            raw_data = data_input
        lines = raw_data.split('\n')

        if template_type not in ("default", "jinja2", "cheetah"):
            return "# ERROR: Unsupported template type selected!"

        if template_type == "default":
            if self.settings and self.settings.default_template_type:
                template_type = self.settings.default_template_type
            else:
                template_type = "cheetah"

        if len(lines) > 0 and lines[0].find("#template=") == 0:
            # Pull the template type out of the first line and then drop it and rejoin them to pass to the template
            # language
            template_type = lines[0].split("=")[1].strip().lower()
            del lines[0]
            raw_data = "\n".join(lines)

        if template_type == "cheetah":
            data_out = self.render_cheetah(raw_data, search_table)
        elif template_type == "jinja2":
            if jinja2_available:
                data_out = self.render_jinja2(raw_data, search_table)
            else:
                return "# ERROR: JINJA2 NOT AVAILABLE. Maybe you need to install python-jinja2?\n"
        else:
            return "# ERROR: UNSUPPORTED TEMPLATE TYPE (%s)" % str(template_type)

        # Now apply some magic post-filtering that is used by "cobbler import" and some other places. Forcing folks to
        # double escape things would be very unwelcome.
        hp = search_table.get("http_port", "80")
        server = search_table.get("server", self.settings.server)
        if hp not in (80, '80'):
            repstr = "%s:%s" % (server, hp)
        else:
            repstr = server
        search_table["http_server"] = repstr

        # string replacements for @@xyz@@ in data_out with prior regex lookups of keys
        regex = r"@@[\S]*?@@"
        regex_matches = re.finditer(regex, data_out, re.MULTILINE)
        matches = set([match.group() for match_num, match in enumerate(regex_matches, start=1)])
        for match in matches:
            data_out = data_out.replace(match, search_table[match.strip("@@")])

        # remove leading newlines which apparently breaks AutoYAST ?
        if data_out.startswith("\n"):
            data_out = data_out.lstrip()

        # if requested, write the data out to a file
        if out_path is not None:
            utils.mkdir(os.path.dirname(out_path))
            with open(out_path, "w+") as file_descriptor:
                file_descriptor.write(data_out)

        return data_out

    def render_cheetah(self, raw_data, search_table: dict) -> str:
        """
        Render data_input back into a file.

        :param raw_data: Is the template code which is not rendered into the result.
        :param search_table: is a dict of metadata keys and values (though results are always returned)
        :return: The rendered Cheetah Template.
        """

        self.check_for_invalid_imports(raw_data)

        # Backward support for Cobbler's legacy (and slightly more readable) template syntax.
        raw_data = raw_data.replace("TEMPLATE::", "$")

        # HACK: the autoinstall_meta field may contain nfs://server:/mount in which case this is likely WRONG for
        # automated installation files, which needs the NFS directive instead. Do this to make the templates work.
        newdata = ""
        if "tree" in search_table and search_table["tree"].startswith("nfs://"):
            for line in raw_data.split("\n"):
                if line.find("--url") != -1 and line.find("url ") != -1:
                    rest = search_table["tree"][6:]  # strip off "nfs://" part
                    try:
                        (server, directory) = rest.split(":", 2)
                    except Exception as e:
                        raise CX("Invalid syntax for NFS path given during import: %s" % search_table["tree"]) from e
                    line = "nfs --server %s --dir %s" % (server, directory)
                    # But put the URL part back in so koan can still see what the original value was
                    line += "\n" + "#url --url=%s" % search_table["tree"]
                newdata += line + "\n"
            raw_data = newdata

        # Tell Cheetah not to blow up if it can't find a symbol for something.
        raw_data = "#errorCatcher ListErrors\n" + raw_data

        table_copy = search_table.copy()

        # For various reasons we may want to call a module inside a template and pass it all of the template variables.
        # The variable "template_universe" serves this purpose to make it easier to iterate through all of the variables
        # without using internal Cheetah variables

        search_table.update({
            "template_universe": table_copy
        })

        # Now do full templating scan, where we will also templatify the snippet insertions
        with open(CHEETAH_MACROS_FILE, "r") as macro_file:
            cheetah_macros_content = macro_file.read()
        cheetah_macros = CobblerTemplate.compile(
            source=cheetah_macros_content,
            moduleName="cobbler.template_api",
            className="CheetahMacros")
        template = CobblerTemplate().compile(
            source=raw_data,
            compilerSettings={'useStackFrame': False},
            baseclass=cheetah_macros
        )

        major, minor, release = Cheetah.Version.split('.')[0:3]

        if (int(major), int(minor), int(release)) >= (2, 4, 2):
            template.SNIPPET = functools.partial(template.SNIPPET, template)
            template.read_snippet = functools.partial(template.read_snippet, template)

        try:
            generated_template_class = template(searchList=[search_table])
            data_out = str(generated_template_class)
            self.last_errors = generated_template_class.errorCatcher().listErrors()
            if self.last_errors:
                self.logger.warning("errors were encountered rendering the template")
                self.logger.warning("\n" + pprint.pformat(self.last_errors))
        except Exception as e:
            self.logger.error(utils.cheetah_exc(e))
            raise CX("Error templating file, check cobbler.log for more details")

        return data_out

    def render_jinja2(self, raw_data: str, search_table: dict) -> str:
        """
        Render data_input back into a file.

        :param raw_data: Is the template code which is not rendered into the result.
        :param search_table: is a dict of metadata keys and values
        :return: The rendered Jinja2 Template.
        """

        try:
            if self.settings and self.settings.jinja2_includedir:
                template = jinja2 \
                    .Environment(loader=jinja2.FileSystemLoader(self.settings.jinja2_includedir)) \
                    .from_string(raw_data)
            else:
                template = jinja2.Template(raw_data)
            data_out = template.render(search_table)
        except Exception as exc:
            self.logger.warning("errors were encountered rendering the template")
            self.logger.warning(exc.__str__())
            data_out = "# EXCEPTION OCCURRED DURING JINJA2 TEMPLATE PROCESSING\n"

        return data_out
