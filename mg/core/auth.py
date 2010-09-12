from mg.core.cass import CassandraObject, CassandraObjectList, ObjectNotFoundException
from mg.core import Module
from uuid import uuid4
from wsgiref.handlers import format_date_time
from datetime import datetime
from PIL import Image, ImageDraw, ImageFilter, ImageEnhance
from mg.core.bezier import make_bezier
from mg.core.tools import *
import cStringIO
import time
import re
import random
import hashlib
import cgi

class User(CassandraObject):
    _indexes = {
        "created": [[], "created"],
        "last_login": [[], "last_login"],
        "name": [["name_lower"]],
    }

    def __init__(self, *args, **kwargs):
        kwargs["prefix"] = "User-"
        CassandraObject.__init__(self, *args, **kwargs)

    def indexes(self):
        return User._indexes

class UserList(CassandraObjectList):
    def __init__(self, *args, **kwargs):
        kwargs["prefix"] = "User-"
        kwargs["cls"] = User
        CassandraObjectList.__init__(self, *args, **kwargs)

class UserPermissions(CassandraObject):
    _indexes = {
        "any": [["any"]],
    }

    def __init__(self, *args, **kwargs):
        kwargs["prefix"] = "UserPermissions-"
        CassandraObject.__init__(self, *args, **kwargs)

    def indexes(self):
        return UserPermissions._indexes

    def sync(self):
        self.set("any", "1")

class UserPermissionsList(CassandraObjectList):
    def __init__(self, *args, **kwargs):
        kwargs["prefix"] = "UserPermissions-"
        kwargs["cls"] = UserPermissions
        CassandraObjectList.__init__(self, *args, **kwargs)

class Session(CassandraObject):
    _indexes = {
        "valid_till": [[], "valid_till"],
        "user": [["user"]],
    }

    def __init__(self, *args, **kwargs):
        kwargs["prefix"] = "Session-"
        CassandraObject.__init__(self, *args, **kwargs)

    def indexes(self):
        return Session._indexes

class SessionList(CassandraObjectList):
    def __init__(self, *args, **kwargs):
        kwargs["prefix"] = "Session-"
        kwargs["cls"] = Session
        CassandraObjectList.__init__(self, *args, **kwargs)

class Captcha(CassandraObject):
    _indexes = {
        "valid_till": [[], "valid_till"],
    }

    def __init__(self, *args, **kwargs):
        kwargs["prefix"] = "Captcha-"
        CassandraObject.__init__(self, *args, **kwargs)

    def indexes(self):
        return Captcha._indexes

class CaptchaList(CassandraObjectList):
    def __init__(self, *args, **kwargs):
        kwargs["prefix"] = "Captcha-"
        kwargs["cls"] = Captcha
        CassandraObjectList.__init__(self, *args, **kwargs)

class CookieSession(Module):
    def register(self):
        Module.register(self)
        self.rhook("session.get", self.get)
        self.rhook("session.require_login", self.require_login)

    def get(self, create=False):
        req = self.req()
        sid = req.cookie("mgsess")
        if sid is not None:
            mcid = "SessionCache-%s" % sid
            val = self.app().mc.get(mcid)
            if val is not None:
                return self.obj(Session, sid, val)
            session = self.find(sid)
            if session is not None:
                session.set("valid_till", "%020d" % (time.time() + 90 * 86400))
                session.store()
                self.app().mc.set(mcid, session.data)
                return session
        sid = uuid4().hex
        args = {}
        domain = req.environ.get("HTTP_X_REAL_HOST")
        if domain is not None:
            domain = re.sub(r'^www\.', '', domain)
            args["domain"] = "." + domain
        args["path"] = "/"
        args["expires"] = format_date_time(time.mktime(datetime.now().timetuple()) + 90 * 86400)
        req.set_cookie("mgsess", sid, **args)
        session = self.obj(Session, sid, {})
        if create:
            # newly created session is stored for 24 hour only
            # this interval is increased after the next successful 'get'
            session.set("valid_till", "%020d" % (time.time() + 86400))
            session.store()
        return session

    def find(self, sid):
        try:
            return self.obj(Session, sid)
        except ObjectNotFoundException:
            return None

    def require_login(self):
        session = self.call("session.get")
        if session is None or session.get("user") is None:
            req = self.req()
            self.call("web.redirect", "/auth/login?redirect=%s" % urlencode(req.uri()))
        return session

class PasswordAuthentication(Module):
    def register(self):
        Module.register(self)
        self.rhook("ext-auth.register", self.ext_register)
        self.rhook("ext-auth.captcha", self.ext_captcha)
        self.rhook("ext-auth.logout", self.ext_logout)
        self.rhook("ext-auth.login", self.ext_login)
        self.rhook("session.find_user", self.find_user)

    def ext_register(self):
        req = self.req()
        session = self.call("session.get", True)
        form = self.call("web.form", "socio/form.html")
        name = req.param("name")
        password1 = req.param("password1")
        password2 = req.param("password2")
        captcha = req.param("captcha")
        redirect = req.param("redirect")
        if req.ok():
            if not name:
                form.error("name", self._("Enter your user name"))
            elif not re.match(r'^[A-Za-z0-9_-]+$', name):
                form.error("name", self._("Invalid characters in the name. Only latin letters, numbers, symbols '_' and '-' are allowed"))
            elif self.find_user(name):
                form.error("name", self._("This name is taken already"))
            if not password1:
                form.error("password1", self._("Enter your password"))
            elif len(password1) < 6:
                form.error("password1", self._("Minimal password length - 6 characters"))
            elif not password2:
                form.error("password2", self._("Retype your password"))
            elif password1 != password2:
                form.error("password2", self._("Password don't match. Try again, please"))
                password1 = ""
                password2 = ""
            if not captcha:
                form.error("captcha", self._("Enter numbers from the picture"))
            else:
                try:
                    cap = self.obj(Captcha, session.uuid)
                    if cap.get("number") != captcha:
                        form.error("captcha", self._("Incorrect number"))
                except ObjectNotFoundException:
                    form.error("captcha", self._("Incorrect number"))
            if not form.errors:
                user = self.obj(User)
                now = "%020d" % time.time()
                user.set("created", now)
                user.set("last_login", now)
                user.set("name", name)
                user.set("name_lower", name.lower())
                salt = ""
                letters = "abcdefghijklmnopqrstuvwxyz"
                for i in range(0, 10):
                    salt += random.choice(letters)
                user.set("salt", salt)
                user.set("pass_reminder", re.sub(r'^(..).*$', r'\1...', password1))
                m = hashlib.md5()
                m.update(salt + password1.encode("utf-8"))
                user.set("pass_hash", m.hexdigest())
                user.store()
                session.set("user", user.uuid)
                session.store()
                self.app().mc.delete("SessionCache-%s" % session.uuid)
                if redirect is not None and redirect != "":
                    self.call("web.redirect", redirect)
                redirects = {}
                self.call("auth.redirects", redirects)
                if redirects.has_key("register"):
                    self.call("web.redirect", redirects["register"])
                self.call("web.redirect", "/")
        if redirect is not None:
            form.hidden("redirect", redirect)
        form.input(self._("User name"), "name", name)
        form.password(self._("Password"), "password1", password1)
        form.password(self._("Retype password"), "password2", password2)
        form.input('<img id="captcha" src="/auth/captcha" alt="" /><br />' + self._('Enter a number (6 digits) from the picture'), "captcha", "")
        form.submit(None, None, self._("Register"))
        vars = {
            "title": self._("User registration"),
        }
        self.call("web.response_global", form.html(), vars)

    def ext_captcha(self):
        session = self.call("session.get")
        if session is None:
            self.call("web.forbidden")
        field = 20
        char_w = 35
        char_h = 40
        step = 20
        digits = 6
        jitter = 0.15
        image = Image.new("RGB", (step * (digits - 1) + char_w + field * 2, char_h + field * 2), (255, 255, 255))
        draw = ImageDraw.Draw(image)
        number = ""
        ts = [t / 50.0 for t in range(51)]
        for i in range(0, digits):
            digit = random.randint(0, 9)
            number += str(digit)
            off_x = i * step + field
            off_y = field + char_h * random.uniform(-0.1, 0.1)
            if digit == 0:
                splines = [
                    ((0, 0.33), (0.33, -0.1), (0.67, -0.1), (1, 0.33), (1, 0.67)),
                    ((1, 0.67), (0.67, 1.1), (0.33, 1.1), (0, 0.67), (0, 0.33)),
                ]
            elif digit == 1:
                splines = [
                    ((0, 0.5), (0.6, 0)),
                    ((0.6, 0), (0.6, 1)),
                ]
            elif digit == 2:
                splines = [
                    ((0.1, 0.33), (0.33, -0.1), (0.67, -0.1), (0.9, 0.33)),
                    ((0.9, 0.33), (0.9, 0.66), (0.1, 0.95)),
                    ((0.1, 0.95), (1, 1)),
                ]
            elif digit == 3:
                splines = [
                    ((0, 0.33), (0.33, -0.1), (0.67, -0.1), (1, 0.25), (1, 0.5), (0.33, 0.5)),
                    ((0.33, 0.5), (1, 0.5), (1, 0.75), (0.66, 1.1), (0.33, 1.1), (0, 0.67)),
                ]
            elif digit == 4:
                splines = [
                    ((0, 0), (0, 0.5), (0.8, 0.5)),
                    ((0.8, 0), (0.8, 0.5), (0.8, 1)),
                ]
            elif digit == 5:
                splines = [
                    ((0.8, 0), (0.2, 0), (0.2, 0.5)),
                    ((0.2, 0.5), (0.6, 0.5), (0.8, 0.75), (0.6, 1), (0.2, 1)),
                ]
            elif digit == 6:
                splines = [
                    ((1, 0), (0.67, -0.1), (0.33, -0.1), (0, 0.33), (0, 0.67)),
                    ((0, 0.67), (0.33, 1.1), (0.67, 1.1), (1, 0.67)),
                    ((1, 0.67), (0.67, 0.33), (0.33, 0.33), (0, 0.67))
                ]
            elif digit == 7:
                splines = [
                    ((0, 0), (0.67, 0), (1, 0.33)),
                    ((1, 0.33), (0.5, 0.5), (0.5, 1)),
                ]
            elif digit == 8:
                splines = [
                    ((0.5, 0.5), (0.2, 0.5), (-0.2, 0.67), (0.2, 1), (0.5, 1)),
                    ((0.5, 1), (0.8, 1), (1.2, 0.67), (0.8, 0.5), (0.5, 0.5)),
                    ((0.5, 0.5), (0.2, 0.5), (-0.2, 0.33), (0.2, 0), (0.5, 0)),
                    ((0.5, 0), (0.8, 0), (1.2, 0.33), (0.8, 0.5), (0.5, 0.5)),
                ]
            elif digit == 9:
                splines = [
                    ((0, 1), (0.33, 1.1), (0.67, 1.1), (1, 0.67), (1, 0.33)),
                    ((1, 0.33), (0.67, -0.1), (0.33, -0.1), (0, 0.33)),
                    ((0, 0.33), (0.33, 0.67), (0.67, 0.67), (1, 0.33))
                ]
            points = []
            corrections = {}
            for spline in splines:
                corr = corrections.get(spline[0])
                if corr is None:
                    x1 = spline[0][0] + random.uniform(-jitter, jitter)
                    y1 = spline[0][1] + random.uniform(-jitter, jitter)
                    corrections[spline[0]] = (x1, y1)
                else:
                    x1 = corr[0]
                    y1 = corr[1]
                xys = [(x1, y1)]
                for i in range(1, len(spline)):
                    corr = corrections.get(spline[i])
                    if corr is None:
                        x2 = spline[i][0] + random.uniform(-jitter, jitter)
                        y2 = spline[i][1] + random.uniform(-jitter, jitter)
                        corrections[spline[i]] = (x2, y2)
                    else:
                        x2 = corr[0]
                        y2 = corr[1]
                    xys.append((x2, y2))
                    x1 = x2
                    y1 = y2
                xys = [(x * char_w + off_x, y * char_h + off_y) for x, y in xys]
                bezier = make_bezier(xys)
                points.extend(bezier(ts))
            draw.line(points, fill=(0, 0, 0), width=1)
        del draw
        try:
            captcha = self.obj(Captcha, session.uuid)
        except ObjectNotFoundException:
            captcha = self.obj(Captcha, session.uuid, {})
        captcha.set("number", number)
        captcha.set("valid_till", "%020d" % (time.time() + 86400))
        captcha.store()
        data = cStringIO.StringIO()
        image = image.filter(ImageFilter.MinFilter(3))
        image.save(data, "JPEG")
        self.call("web.response", data.getvalue(), "image/jpeg")

    def find_user(self, name):
        users = self.objlist(UserList, query_index="name", query_equal=name.lower())
        if len(users):
            users.load()
            return users[0]
        else:
            return None

    def ext_logout(self):
        session = self.call("session.get")
        if session is not None and session.get("user"):
            session.delkey("user")
            session.store()
            self.app().mc.delete("SessionCache-%s" % session.uuid)
            req = self.req()
            redirect = req.param("redirect")
            if redirect is not None and redirect != "":
                self.call("web.redirect", redirect)
        self.call("web.redirect", "/")

    def ext_login(self):
        req = self.req()
        form = self.call("web.form", "socio/form.html")
        name = req.param("name")
        password = req.param("password")
        redirect = req.param("redirect")
        if req.ok():
            if not name:
                form.error("name", self._("Enter your user name"))
            else:
                user = self.find_user(name)
                if user is None:
                    form.error("name", self._("User not found"))
            if not password:
                form.error("password", self._("Enter your password"))
            if not form.errors:
                m = hashlib.md5()
                m.update(user.get("salt").encode("utf-8") + password.encode("utf-8"))
                if m.hexdigest() != user.get("pass_hash"):
                    form.error("password", self._("Incorrect password"))
            if not form.errors:
                session = self.call("session.get", True)
                session.set("user", user.uuid)
                session.store()
                self.app().mc.delete("SessionCache-%s" % session.uuid)
                if redirect is not None and redirect != "":
                    self.call("web.redirect", redirect)
                redirects = {}
                self.call("auth.redirects", redirects)
                if redirects.has_key("login"):
                    self.call("web.redirect", redirects["login"])
                self.call("web.redirect", "/")
        if redirect is not None:
            form.hidden("redirect", redirect)
        form.input(self._("User name"), "name", name)
        form.password(self._("Password"), "password", password)
        form.submit(None, None, self._("Log in"))
        form.add_message_bottom('<a href="/auth/register?redirect=%s">%s</a>' % (urlencode(redirect), self._("Register")))
        vars = {
            "title": self._("User login"),
        }
        self.call("web.response_global", form.html(), vars)

class Authorization(Module):
    def register(self):
        Module.register(self)
        self.rhook("auth.permissions", self.auth_permissions)
        self.rhook("session.require_permission", self.require_permission)
        self.admin_uuid = self.app().inst.config.get("admin_user")
        self.rhook("menu-admin-root.index", self.menu_root_index)
        self.rhook("menu-admin-security.index", self.menu_security_index)
        self.rhook("ext-admin-auth.permissions", self.admin_permissions)
        self.rhook("headmenu-admin-auth.permissions", self.headmenu_permissions)
        self.rhook("ext-admin-auth.editpermissions", self.admin_editpermissions)
        self.rhook("headmenu-admin-auth.editpermissions", self.headmenu_editpermissions)
        self.rhook("ext-admin-auth.edituserpermissions", self.admin_edituserpermissions)
        self.rhook("headmenu-admin-auth.edituserpermissions", self.headmenu_edituserpermissions)
        self.rhook("permissions.list", self.permissions_list)

    def permissions_list(self, perms):
        perms.append({"id": "permissions", "name": self._("User permissions editor")})

    def auth_permissions(self, user_id):
        perms = {}
        if user_id:
            if user_id == self.admin_uuid:
                perms["admin"] = True
            try:
                p = self.obj(UserPermissions, user_id)
                for key in p.get("perms").keys():
                    perms[key] = True
            except ObjectNotFoundException:
                pass
        return perms

    def require_permission(self, perm):
        req = self.req()
        if not req.has_access(perm):
            self.call("web.forbidden")

    def menu_root_index(self, menu):
        menu.append({"id": "security.index", "text": self._("Security")})

    def menu_security_index(self, menu):
        req = self.req()
        if req.has_access("permissions"):
            menu.append({"id": "auth/permissions", "text": self._("Permissions"), "leaf": True})

    def admin_permissions(self):
        self.call("session.require_permission", "permissions")
        permissions_list = []
        self.call("permissions.list", permissions_list)
        users = []
        user_permissions = self.objlist(UserPermissionsList, query_index="any", query_equal="1")
        print "user_permissions: %s" % user_permissions
        if len(user_permissions):
            user_permissions.load()
            perms = dict([(obj.uuid, obj.get("perms")) for obj in user_permissions])
            usr = self.objlist(UserList, perms.keys())
            usr.load()
            for u in usr:
                grant_list = []
                p = perms[u.uuid]
                for perm in permissions_list:
                    if p.get(perm["id"]):
                        grant_list.append(perm["name"])
                users.append({"id": u.uuid, "name": cgi.escape(u.get("name")), "permissions": "<br />".join(grant_list)})
        vars = {
            "editpermissions": self._("Edit permissions of a user"),
            "user_name": self._("User name"),
            "permissions": self._("Permissions"),
            "edit": self._("edit"),
            "editing": self._("Editing"),
            "users": users,
        }
        self.call("admin.response_template", "admin/auth/permissions.html", vars)

    def headmenu_permissions(self, args):
        return self._("User permissions")

    def admin_editpermissions(self):
        self.call("session.require_permission", "permissions")
        req = self.req()
        name = req.param("name")
        if req.ok():
            errors = {}
            if not name:
                errors["name"] = self._("Enter user name")
            else:
                user = self.call("session.find_user", name)
                if not user:
                    errors["name"] = self._("User not found")
                else:
                    return req.jresponse({"success": True, "redirect": "auth/edituserpermissions/%s" % user.uuid})
            return req.jresponse({"success": False, "errors": errors})
        fields = [
            {"name": "name", "label": self._("User name"), "value": name},
        ]
        buttons = [{"text": self._("Search")}]
        return self.call("admin.form", fields=fields, buttons=buttons)

    def headmenu_editpermissions(self, args):
        return [self._("Edit permissions of a user"), "auth/permissions"]

    def admin_edituserpermissions(self):
        self.call("session.require_permission", "permissions")
        req = self.req()
        try:
            user = self.obj(User, req.args)
        except ObjectNotFoundException:
            self.call("web.not_found")
        perms = []
        self.call("permissions.list", perms)
        try:
            user_permissions = self.obj(UserPermissions, req.args)
        except ObjectNotFoundException:
            user_permissions = self.obj(UserPermissions, req.args, {})
        if req.ok():
            perm_values = {}
            for perm in perms:
                if req.param("perm%s" % perm["id"]):
                    perm_values[perm["id"]] = True
            if perm_values:
                user_permissions.set("perms", perm_values)
                user_permissions.sync()
                user_permissions.store()
            else:
                user_permissions.remove()
            return req.jresponse({"success": True, "redirect": "auth/permissions"})
        else:
            perm_values = user_permissions.get("perms")
            if not perm_values:
                perm_values = {}
        fields = []
        for perm in perms:
            fields.append({"name": "perm%s" % perm["id"], "label": perm["name"], "type": "checkbox", "checked": perm_values.get(perm["id"])})
        return self.call("admin.form", fields=fields)

    def headmenu_edituserpermissions(self, args):
        user = self.obj(User, args)
        return [cgi.escape(user.get("name")), "auth/editpermissions"]
