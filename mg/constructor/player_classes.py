from mg.constructor import *
from mg.constructor.interface_classes import *
from mg.core.money_classes import *
import re

re_money_script_field = re.compile(r'^(balance|available)_(\S+)$')

# Database objects

class DBPlayer(CassandraObject):
    _indexes = {
        "created": [[], "created"],
        "active": [["active"], "last_visit"],
    }

    def __init__(self, *args, **kwargs):
        kwargs["clsprefix"] = "Player-"
        CassandraObject.__init__(self, *args, **kwargs)

    def indexes(self):
        return DBPlayer._indexes

class DBPlayerList(CassandraObjectList):
    def __init__(self, *args, **kwargs):
        kwargs["clsprefix"] = "Player-"
        kwargs["cls"] = DBPlayer
        CassandraObjectList.__init__(self, *args, **kwargs)

class DBCharImage(CassandraObject):
    _indexes = {}

    def __init__(self, *args, **kwargs):
        kwargs["clsprefix"] = "CharImage-"
        CassandraObject.__init__(self, *args, **kwargs)

    def indexes(self):
        return DBCharImage._indexes

class DBCharImageList(CassandraObjectList):
    def __init__(self, *args, **kwargs):
        kwargs["clsprefix"] = "CharImage-"
        kwargs["cls"] = DBCharImage
        CassandraObjectList.__init__(self, *args, **kwargs)

class DBCharacter(CassandraObject):
    _indexes = {
        "created": [[], "created"],
        "player": [["player"], "created"],
        "admin": [["admin"]]
    }

    def __init__(self, *args, **kwargs):
        kwargs["clsprefix"] = "Character-"
        CassandraObject.__init__(self, *args, **kwargs)

    def indexes(self):
        return DBCharacter._indexes

class DBCharacterList(CassandraObjectList):
    def __init__(self, *args, **kwargs):
        kwargs["clsprefix"] = "Character-"
        kwargs["cls"] = DBCharacter
        CassandraObjectList.__init__(self, *args, **kwargs)

class DBCharacterForm(CassandraObject):
    _indexes = {
    }

    def __init__(self, *args, **kwargs):
        kwargs["clsprefix"] = "CharacterForm-"
        CassandraObject.__init__(self, *args, **kwargs)

    def indexes(self):
        return DBCharacterForm._indexes

class DBCharacterFormList(CassandraObjectList):
    def __init__(self, *args, **kwargs):
        kwargs["clsprefix"] = "CharacterForm-"
        kwargs["cls"] = DBCharacterForm
        CassandraObjectList.__init__(self, *args, **kwargs)

class DBCharacterOnline(CassandraObject):
    _indexes = {
        "all": [[]]
    }

    def __init__(self, *args, **kwargs):
        kwargs["clsprefix"] = "CharacterOnline-"
        CassandraObject.__init__(self, *args, **kwargs)

    def indexes(self):
        return DBCharacterOnline._indexes

class DBCharacterOnlineList(CassandraObjectList):
    def __init__(self, *args, **kwargs):
        kwargs["clsprefix"] = "CharacterOnline-"
        kwargs["cls"] = DBCharacterOnline
        CassandraObjectList.__init__(self, *args, **kwargs)

class DBCharacterSettings(CassandraObject):
    _indexes = {
    }

    def __init__(self, *args, **kwargs):
        kwargs["clsprefix"] = "CharacterSettings-"
        CassandraObject.__init__(self, *args, **kwargs)

    def indexes(self):
        return DBCharacterSettings._indexes

class DBCharacterSettingsList(CassandraObjectList):
    def __init__(self, *args, **kwargs):
        kwargs["clsprefix"] = "CharacterSettings-"
        kwargs["cls"] = DBCharacterSettings
        CassandraObjectList.__init__(self, *args, **kwargs)

# Business logic objects

class Money(MemberMoney):
    def script_attr(self, attr):
        m = re_money_script_field.match(attr)
        if m:
            field, currency = m.group(1, 2)
            if field == "balance":
                return self.balance(currency)
            elif field == "available":
                return self.available(currency)
        raise AttributeError(attr)

class Character(Module):
    def __init__(self, app, uuid, fqn="mg.constructor.players.Character"):
        Module.__init__(self, app, fqn)
        self.uuid = uuid

    @property
    def db_character(self):
        try:
            return self._db_character
        except AttributeError:
            self._db_character = self.obj(DBCharacter, self.uuid)
            return self._db_character

    @property
    def db_charimage(self):
        try:
            return self._db_charimage
        except AttributeError:
            self._db_charimage = self.obj(DBCharImage, self.uuid)
            return self._db_charimage

    @property
    def valid(self):
        try:
            self.db_character
        except ObjectNotFoundException:
            return False
        else:
            return True

    @property
    def db_user(self):
        try:
            return self._db_user
        except AttributeError:
            self._db_user = self.obj(User, self.uuid)
            return self._db_user

    @property
    def db_form(self):
        try:
            return self._db_form
        except AttributeError:
            self._db_form = self.obj(DBCharacterForm, self.uuid, silent=True)
            return self._db_form

    @property
    def name(self):
        try:
            return self._name
        except AttributeError:
            self._name = self.db_user.get("name")
            return self._name

    @property
    def player(self):
        try:
            return self._player
        except AttributeError:
            uuid = self.db_character.get("player")
            if uuid:
                try:
                    req = self.req()
                except AttributeError:
                    return Player(self.app(), uuid)
                else:
                    try:
                        players = req.players
                    except AttributeError:
                        players = {}
                        req.players = players
                    try:
                        return players[uuid]
                    except KeyError:
                        obj = Player(self.app(), uuid)
                        players[uuid] = obj
                        return obj
            else:
                self._player = None
            return self._player

    @property
    def sex(self):
        try:
            return self._sex
        except AttributeError:
            self._sex = self.db_user.get("sex")
            return self._sex

    def html(self, purpose="default"):
        # local cache
        try:
            html = self._html
        except AttributeError:
            html = {}
            self._html = html
        try:
            return html[purpose]
        except KeyError:
            pass
        # memcached
        mc = self.app().mc
        mcid = "Character.%s.html.%s%s" % (self.uuid, purpose, mc.ver(["character-names", "character-name.%s" % self.uuid]))
        val = mc.get(mcid)
        if not val:
            # evaluation
            params = {
                self.uuid: {}
            }
            template = self.conf("character.name-template-%s" % purpose)
            if template is None:
                pinfo = self.call("characters.name-purpose-%s" % purpose)
                template = pinfo["default"] if pinfo else "{NAME}"
            self.call("characters.name-params", [self], params)
            params = params[self.uuid]
            self.call("characters.name-fixup", self, purpose, params)
            val = self.call("characters.name-render", template, params)
            mc.set(mcid, val)
        html[purpose] = val
        return val

    def invalidate_name(self):
        self.app().mc.incr_ver("character-name.%s" % self.uuid)

    @property
    def tech_online(self):
        try:
            return self._tech_online
        except AttributeError:
            try:
                self.obj(DBCharacterOnline, self.uuid)
            except ObjectNotFoundException:
                self._tech_online = False
            else:
                self._tech_online = True
            return self._tech_online

    @property
    def lock(self):
        return self.lock(["character.%s" % self.uuid])

    @property
    def location(self):
        try:
            return self._location[0]
        except AttributeError:
            self._location = self.call("locations.character_get", self) or [None, None, None]
            return self._location[0]

    @property
    def instance(self):
        try:
            return self._location[1]
        except AttributeError:
            self._location = self.call("locations.character_get", self) or [None, None, None]
            return self._location[1]

    @property
    def location_delay(self):
        try:
            return self._location[2]
        except AttributeError:
            self._location = self.call("locations.character_get", self) or [None, None, None]
            return self._location[2]

    def set_location(self, location, instance=None, delay=None):
        old_location = self.location
        old_instance = self.instance
        self.call("locations.character_before_set", self, location, instance)
        self.call("locations.character_set", self, location, instance, delay)
        self._location = [location, instance, delay]
        self.call("locations.character_after_set", self, old_location, old_instance)

    @property
    def db_settings(self):
        try:
            return self._db_settings
        except AttributeError:
            self._db_settings = self.obj(DBCharacterSettings, self.uuid, silent=True)
            return self._db_settings

    @property
    def sessions(self):
        try:
            return self._sessions
        except AttributeError:
            self._sessions = []
            self.call("session.character-sessions", self, self._sessions)
            return self._sessions

    @property
    def money(self):
        try:
            return self._money
        except AttributeError:
            self._money = Money(self.app(), self.uuid)
            return self._money

    @property
    def settings(self):
        try:
            return self._settings
        except AttributeError:
            self._settings = self.obj(DBCharacterSettings, self.uuid, silent=True)
            return self._settings

    def script_attr(self, attr):
        if attr == "id":
            return self.uuid
        elif attr == "player":
            return self.player
        elif attr == "money":
            return self.money
        elif attr == "location":
            return self.location
        elif attr == "tech_online":
            return self.tech_online
        elif attr == "online":
            return self.tech_online
        elif attr == "name":
            return self.name
        elif attr == "chatname":
            return "[ch:%s]" % self.uuid
        elif attr == "sex":
            return self.sex
        elif attr == "mod":
            return self.call("modifiers.obj", self.uuid)
        elif attr == "anyperm":
            perms = self.call("auth.permissions", self.uuid)
            return 1 if perms and len(perms) else 0
        else:
            raise AttributeError(attr)

    @property
    def restraints(self):
        try:
            return self._restraints
        except AttributeError:
            restraints = {}
            self.call("restraints.check", self.uuid, restraints)
            self._restraints = restraints
            return restraints

    def info_avatar(self):
        try:
            return self._info_avatar
        except AttributeError:
            self._info_avatar = self.call("character.info-avatar", self)
            return self._info_avatar

    def page_avatar(self):
        try:
            return self._page_avatar
        except AttributeError:
            self._page_avatar = self.call("character.page-avatar", self)
            return self._page_avatar

class Player(Module):
    def __init__(self, app, uuid, fqn="mg.constructor.players.Player"):
        Module.__init__(self, app, fqn)
        self.uuid = uuid

    @property
    def db_player(self):
        try:
            return self._db_player
        except AttributeError:
            self._db_player = self.obj(DBPlayer, self.uuid)
            return self._db_player

    @property
    def valid(self):
        try:
            self.db_player
        except ObjectNotFoundException:
            return False
        else:
            return True

    @property
    def db_user(self):
        try:
            return self._db_user
        except AttributeError:
            self._db_user = self.obj(User, self.uuid)
            return self._db_user

    @property
    def email(self):
        try:
            return self._email
        except AttributeError:
            self._email = self.db_user.get("email")
            return self._email

    def script_attr(self, attr):
        if attr == "id":
            return self.uuid
        elif attr == "mod":
            return self.call("modifiers.obj", self.uuid)
        else:
            raise AttributeError(attr)

    @property
    def characters(self):
        try:
            return self._characters
        except AttributeError:
            try:
                req = self.req()
                try:
                    characters = req.character
                except AttributeError:
                    characters = {}
                    req.characters = characters
            except AttributeError:
                characters = {}
            lst = self.objlist(DBCharacterList, query_index="player", query_equal=self.uuid)
            chars = []
            for ent in lst:
                character = characters.get(ent.uuid)
                if not character:
                    character = Character(self.app(), ent.uuid)
                    characters[ent.uuid] = character
                chars.append(character)
            self._characters = chars
            return chars

class Characters(Module):
    def __init__(self, app, fqn="mg.constructor.players.Characters"):
        Module.__init__(self, app, fqn)

    @property
    def tech_online(self):
        try:
            return self._tech_online
        except AttributeError:
            self._tech_online = []
            self.call("auth.characters-tech-online", self._tech_online)
            return self._tech_online
