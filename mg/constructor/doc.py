#!/usr/bin/python2.6

# This file is a part of Metagam project.
#
# Metagam is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# any later version.
# 
# Metagam is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
# 
# You should have received a copy of the GNU General Public License
# along with Metagam.  If not, see <http://www.gnu.org/licenses/>.

import mg
from mg import *
import re
from mg.constructor.script_classes import *

re_valid_docfile = re.compile(r'^[a-z0-9\-]+(/[a-z0-9\-]+)*/?$')
re_not_found = re.compile(r'^file error - .*: not found$')
re_doc_tag = re.compile(r'^\s*<!--\s*doc\.([a-z_]+)\s+(.*?)\s*-->\s*(.*)', re.DOTALL)
re_valid_template = re.compile(r'^[a-z0-9][a-z0-9\-]*\.(?:html|js)$')

class Documentation(Module):
    def register(self):

        self.rhook("ext-doc.index", self.index, priv="public")
        self.rhook("ext-doc.game-template", self.game_template, priv="public")
        self.rhook("ext-doc.socio-template", self.socio_template, priv="public")
        self.rhook("ext-doc.combat-template", self.combat_template, priv="public")
        self.rhook("ext-doc.expression-parser", self.expression_parser, priv="public")
        self.rhook("ext-doc.handler", self.handler, priv="public")

    def index(self):
        req = self.req()
        req.args = "index"
        return self.handler()

    def handler(self):
        req = self.req()
        m = re_valid_docfile.match(req.args)
        if not m:
            self.call("web.not_found")
        lang = self.call("l10n.lang")
        vars = {
            "lang": lang,
            "htmlmeta": {},
            "main_host": self.main_host
        }
        try:
            content = self.call("web.parse_template", "constructor/docs/%s/%s.html" % (lang, req.args), vars)
        except TemplateException as e:
            if re_not_found.match(str(e)):
                self.call("web.not_found")
            else:
                raise
        while True:
            m = re_doc_tag.search(content)
            if not m:
                break
            tag, value, content = m.group(1, 2, 3)
            if tag == "keywords" or tag == "description":
                vars["htmlmeta"][tag] = value
            else:
                vars[tag] = value
        menu = []
        while vars.get("parent"):
            try:
                with open("%s/templates/constructor/docs/%s/%s.html" % (mg.__path__[0], lang, vars["parent"])) as f:
                    v = {}
                    for line in f:
                        m = re_doc_tag.search(line)
                        if not m:
                            break
                        tag, value = m.group(1, 2)
                        v[tag] = value
                    if v.get("short_title"):
                        menu.insert(0, {"href": "/doc/%s" % vars["parent"], "html": v["short_title"]})
                    elif v.get("title"):
                        menu.insert(0, {"href": "/doc/%s" % vars["parent"], "html": v["title"]})
                    vars["parent"] = v.get("parent")
            except IOError:
                vars["parent"] = None
        if len(menu):
            menu.append({"html": vars.get("short_title", vars.get("title"))})
            menu[-1]["lst"] = True
            vars["menu_left"] = menu
        self.call("socio.response", '<div class="doc-content">%s</div>' % content, vars)

    def game_template(self):
        req = self.req()
        if not re_valid_template.match(req.args):
            self.call("web.not_found")
        try:
            vars = {
                "title": '%s - %s' % (req.args, self._("Game interface template")),
            }
            with open("%s/templates/game/%s" % (mg.__path__[0], req.args)) as f:
                content = re.sub(r'\n', '<br />', htmlescape(f.read()))
                self.call("socio.response", u'<div class="doc-content"><h1>%s</h1><pre class="doc-code-sample">%s</pre><p><a href="/doc/design/templates">%s</a></div>' % (req.args, content, self._("Description of the templates engine")), vars)
        except IOError:
            self.call("web.not_found")

    def socio_template(self):
        req = self.req()
        if not re_valid_template.match(req.args):
            self.call("web.not_found")
        try:
            vars = {
                "title": '%s - %s' % (req.args, self._("Socio interface template")),
            }
            with open("%s/templates/socio/%s" % (mg.__path__[0], req.args)) as f:
                content = re.sub(r'\n', '<br />', htmlescape(f.read()))
                self.call("socio.response", u'<div class="doc-content"><h1>%s</h1><pre class="doc-code-sample">%s</pre><p><a href="/doc/design/templates">%s</a></div>' % (req.args, content, self._("Description of the templates engine")), vars)
        except IOError:
            self.call("web.not_found")

    def combat_template(self):
        req = self.req()
        if not re_valid_template.match(req.args):
            self.call("web.not_found")
        try:
            vars = {
                "title": '%s - %s' % (req.args, self._("Combat interface template")),
            }
            with open("%s/templates/combat/%s" % (mg.__path__[0], req.args)) as f:
                content = re.sub(r'\n', '<br />', htmlescape(f.read()))
                self.call("socio.response", u'<div class="doc-content"><h1>%s</h1><pre class="doc-code-sample">%s</pre><p><a href="/doc/design/templates">%s</a></div>' % (req.args, content, self._("Description of the templates engine")), vars)
        except IOError:
            self.call("web.not_found")

    def expression_parser(self):
        req = self.req()
        form = self.call("web.form")
        text = req.param("text").strip()
        if req.ok():
            try:
                expression = self.call("script.parse-expression", text)
            except ScriptParserError as e:
                html = e.val.format(**e.kwargs)
                if e.exc:
                    html += "\n%s" % e.exc
                form.error("text", html)
            else:
                form.add_message_top(u'<pre>%s</pre>' % htmlescape(json.dumps(expression, indent=4)))
        form.input(self._("Expression"), "text", text)
        form.submit(None, None, self._("formbtn///Parse"))
        vars = {
            "title": self._("Online script parser"),
            "menu_left": [
                {"href": "/doc", "html": self._("List of categories")},
                {"href": "/doc/script", "html": self._("Scripting engine")},
                {"html": self._("Online script parser"), "lst": True}
            ]
        }
        self.call("socio.response", form.html(vars), vars)
