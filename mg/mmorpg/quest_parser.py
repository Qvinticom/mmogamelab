from mg.core import Parsing
from mg.constructor.script_classes import *

re_valid_identifier = re.compile(r'^[a-z_][a-z0-9_]*$', re.IGNORECASE)
re_param = re.compile(r'^p_([a-z_][a-z0-9_]*)$', re.IGNORECASE)

# To add a new event, condition or action:
#   1. create TokenXXX class
#   2. assign it a terminal symbol: syms["xxx"] = TokenXXX
#   3. write the syntax rule
#   4. write unparsing rule in mg.mmorpg.quests
#   5. implement the feature

class TokenEvent(Parsing.Token):
    "%token event"

class TokenTeleported(Parsing.Token):
    "%token teleported"

class TokenMessage(Parsing.Token):
    "%token message"

class TokenError(Parsing.Token):
    "%token error"

class TokenRequire(Parsing.Token):
    "%token require"

class TokenCall(Parsing.Token):
    "%token call"

class TokenGive(Parsing.Token):
    "%token give"

class TokenIf(Parsing.Token):
    "%token if"

class TokenElse(Parsing.Token):
    "%token else"

class TokenSet(Parsing.Token):
    "%token set"

class TokenFinish(Parsing.Token):
    "%token finish" 

class TokenFail(Parsing.Token):
    "%token fail"

class TokenLock(Parsing.Token):
    "%token lock"

class TokenExpired(Parsing.Token):
    "%token expired"

class TokenTimer(Parsing.Token):
    "%token timer"

class TokenTimeout(Parsing.Token):
    "%token timeout"

class TokenItemUsed(Parsing.Token):
    "%token itemused"

class AttrKey(Parsing.Nonterm):
    "%nonterm"
    def reduceIdentifier(self, identifier):
        "%reduce identifier"
        self.val = identifier.val

    def reduceEvent(self, event):
        "%reduce event"
        self.val = "event"

    def reduceTimeout(self, event):
        "%reduce timeout"
        self.val = "timeout"

class Attrs(Parsing.Nonterm):
    "%nonterm"
    def reduceEmpty(self):
        "%reduce"
        self.val = {}
    
    def reduceAttr(self, attrs, key, a, value):
        "%reduce Attrs AttrKey assign scalar"
        if key.val in attrs.val:
            raise Parsing.SyntaxError(attrs.script_parser._("Attribute '%s' was specified twice") % key.val)
        self.val = attrs.val.copy()
        self.val[key.val] = value.val

class ExprAttrs(Parsing.Nonterm):
    "%nonterm"
    def reduceEmpty(self):
        "%reduce"
        self.val = {}
    
    def reduceAttr(self, attrs, key, a, expr):
        "%reduce Attrs AttrKey assign Expr"
        if key.val in attrs.val:
            raise Parsing.SyntaxError(attrs.script_parser._("Attribute '%s' was specified twice") % key.val)
        self.val = attrs.val.copy()
        self.val[key.val] = expr.val

def get_attr(any_obj, obj_name, attrs, attr, require=False):
    val = attrs.val.get(attr)
    if val is None:
        if require:
            raise Parsing.SyntaxError(any_obj.script_parser._("Attribute '{attr}' is required in the '{obj}'").format(obj=obj_name, attr=attr))
    return val

def get_str_attr(any_obj, obj_name, attrs, attr, require=False):
    val = get_attr(any_obj, obj_name, attrs, attr, require)
    if val is not None and type(val) != str and type(val) != unicode:
        raise Parsing.SyntaxError(any_obj.script_parser._("Attribute '{attr}' in the '{obj}' must be a string").format(obj=obj_name, attr=attr))
    return val

def validate_attrs(any_obj, obj_name, attrs, valid_attrs):
    for k, v in attrs.val.iteritems():
        if k not in valid_attrs:
            raise Parsing.SyntaxError(any_obj.script_parser._("'{obj}' has no attribute '{attr}'").format(obj=obj_name, attr=k))

# ============================
#          EVENTS
# ============================
class EventType(Parsing.Nonterm):
    "%nonterm"
    def reduceEvent(self, ev, eventid):
        "%reduce event scalar"
        if type(eventid.val) != str and type(eventid.val) != unicode:
            raise Parsing.SyntaxError(any_obj.script_parser._("Event id must be a string"))
        elif not re_valid_identifier.match(eventid.val):
            raise Parsing.SyntaxError(any_obj.script_parser._("Event identifier must start with latin letter or '_'. Other symbols may be latin letters, digits or '_'"))
        self.val = [["event", eventid.val], None]

    def reduceTeleported(self, ev, attrs):
        "%reduce teleported Attrs"
        validate_attrs(ev, "teleported", attrs, ["from", "to"])
        self.val = [["teleported"], attrs.val]

    def reduceExpired(self, ev, modid):
        "%reduce expired scalar"
        if type(modid.val) != str and type(modid.val) != unicode:
            raise Parsing.SyntaxError(any_obj.script_parser._("Modifier id must be a string"))
        elif not re_valid_identifier.match(modid.val):
            raise Parsing.SyntaxError(any_obj.script_parser._("Modifier identifier must start with latin letter or '_'. Other symbols may be latin letters, digits or '_'"))
        self.val = [["expired", "mod", modid.val], None]

    def reduceTimeout(self, ev, timerid):
        "%reduce timeout scalar"
        if type(timerid.val) != str and type(timerid.val) != unicode:
            raise Parsing.SyntaxError(any_obj.script_parser._("Timer id must be a string"))
        elif not re_valid_identifier.match(timerid.val):
            raise Parsing.SyntaxError(any_obj.script_parser._("Timer identifier must start with latin letter or '_'. Other symbols may be latin letters, digits or '_'"))
        self.val = [["expired", "timer", timerid.val], None]

    def reduceItemUsed(self, ev, action):
        "%reduce itemused scalar"
        if type(action.val) != str and type(action.val) != unicode:
            raise Parsing.SyntaxError(any_obj.script_parser._("Action code must be a string"))
        elif not re_valid_identifier.match(action.val):
            raise Parsing.SyntaxError(any_obj.script_parser._("Action code must start with latin letter or '_'. Other symbols may be latin letters, digits or '_'"))
        self.val = [["item", action.val], None]

# ============================
#          ACTIONS
# ============================
class QuestAction(Parsing.Nonterm):
    "%nonterm"
    def reduceMessage(self, msg, expr):
        "%reduce message scalar"
        self.val = ["message", msg.script_parser.parse_text(expr.val, msg.script_parser._("action///Quest message"))]

    def reduceError(self, err, expr):
        "%reduce error scalar"
        self.val = ["error", err.script_parser.parse_text(expr.val, err.script_parser._("action///Quest error"))]

    def reduceRequire(self, req, expr):
        "%reduce require Expr"
        self.val = ["require", expr.val]

    def reduceCall(self, call, attrs):
        "%reduce call Attrs"
        event = get_str_attr(call, "call", attrs, "event", require=True)
        quest = get_str_attr(call, "call", attrs, "quest")
        validate_attrs(call, "call", attrs, ["quest", "event"])
        if not re_valid_identifier.match(event):
            raise Parsing.SyntaxError(any_obj.script_parser._("Event identifier must start with latin letter or '_'. Other symbols may be latin letters, digits or '_'"))
        if quest:
            if not re_valid_identifier.match(quest):
                raise Parsing.SyntaxError(any_obj.script_parser._("Quest identifier must start with latin letter or '_'. Other symbols may be latin letters, digits or '_'"))
            self.val = ["call", quest, event]
        else:
            self.val = ["call", event]

    def reduceGive(self, cmd, attrs):
        "%reduce give ExprAttrs"
        item = attrs.val.get("item")
        if not item:
            raise Parsing.SyntaxError(cmd.script_parser._("Attribute '{attr}' is required in the '{obj}'").format(attr="item", obj="give"))
        mods = {}
        for key, val in attrs.val.iteritems():
            if key == "item" or key == "quantity":
                continue
            m = re_param.match(key)
            if m:
                param = m.group(1)
                pinfo = cmd.script_parser.call("item-types.param", param)
                if not pinfo:
                    raise Parsing.SyntaxError(cmd.script_parser._("Items has no parameter %s") % param)
                elif pinfo.get("type", 0) != 0:
                    raise Parsing.SyntaxError(cmd.script_parser._("Parameter %s is not stored in the database") % param)
                mods[param] = val
            else:
                raise Parsing.SyntaxError(cmd.script_parser._("'{obj}' has no attribute '{attr}'").format(obj="give", attr=key))
        item = get_str_attr(cmd, "give", attrs, "item", require=True)
        quantity = get_attr(cmd, "give", attrs, "quantity")
        if quantity is None:
            quantity = 1
        self.val = ["giveitem", item, mods, quantity]

    def reduceIf(self, cmd, expr, curlyleft, actions, curlyright):
        "%reduce if Expr curlyleft QuestActions curlyright"
        self.val = ["if", expr.val, actions.val]

    def reduceIfElse(self, cmd, expr, curlyleft1, actions1, curlyright1, els, curlyleft2, actions2, curlyright2):
        "%reduce if Expr curlyleft QuestActions curlyright else curlyleft QuestActions curlyright"
        self.val = ["if", expr.val, actions1.val, actions2.val]

    def reduceSet(self, st, lvalue, assign, rvalue):
        "%reduce set Expr assign Expr"
        if type(lvalue.val) != list or lvalue.val[0] != ".":
            raise Parsing.SyntaxError(assign.script_parser._("Invalid usage of assignment operator"))
        self.val = ["set", lvalue.val[1], lvalue.val[2], rvalue.val]

    def reduceFinish(self, cmd):
        "%reduce finish"
        self.val = ["destroy", True]

    def reduceFail(self, cmd):
        "%reduce fail"
        self.val = ["destroy", False]

    def reduceLock(self, cmd, attrs):
        "%reduce lock ExprAttrs"
        timeout = get_attr(cmd, "lock", attrs, "timeout")
        validate_attrs(cmd, "lock", attrs, ["timeout"])
        self.val = ["lock", timeout]

    def reduceTimer(self, cmd, attrs):
        "%reduce timer ExprAttrs"
        tid = get_str_attr(cmd, "timer", attrs, "id", require=True)
        if not re_valid_identifier.match(tid):
            raise Parsing.SyntaxError(cmd.script_parser._("Timer identifier must start with latin letter or '_'. Other symbols may be latin letters, digits or '_'"))
        timeout = get_attr(cmd, "timer", attrs, "timeout", require=True)
        validate_attrs(cmd, "timer", attrs, ["id", "timeout"])
        self.val = ["timer", tid, timeout]

class QuestActions(Parsing.Nonterm):
    "%nonterm"
    def reduceEmpty(self):
        "%reduce"
        self.val = []

    def reduceAction(self, actions, action):
        "%reduce QuestActions QuestAction"
        self.val = actions.val + [action.val]

class QuestHandlers(Parsing.Nonterm):
    "%nonterm"
    def reduceEmpty(self):
        "%reduce"
        self.val = []
    
    def reduceHandler(self, handlers, evtype, cl, actions, cr):
        "%reduce QuestHandlers EventType curlyleft QuestActions curlyright"
        info = {
            "type": evtype.val[0]
        }
        if actions.val:
            info["act"] = actions.val
        if evtype.val[1]:
            info["attrs"] = evtype.val[1]
        self.val = handlers.val + [["hdl", info]]

class QuestState(Parsing.Nonterm):
    "%nonterm"
    def reduce(self, handlers):
        "%reduce QuestHandlers"
        self.val = ["state", {}]
        if handlers.val:
            self.val[1]["hdls"] = handlers.val

# This is the start symbol; there can be only one such class in the grammar.
class Result(Parsing.Nonterm):
    "%start"
    def reduce(self, e):
        "%reduce QuestState"
        raise ScriptParserResult(e.val)

class QuestScriptParser(ScriptParser):
    syms = ScriptParser.syms.copy()
    syms["event"] = TokenEvent
    syms["message"] = TokenMessage
    syms["error"] = TokenError
    syms["teleported"] = TokenTeleported
    syms["require"] = TokenRequire
    syms["call"] = TokenCall
    syms["give"] = TokenGive
    syms["if"] = TokenIf
    syms["else"] = TokenElse
    syms["set"] = TokenSet
    syms["finish"] = TokenFinish
    syms["fail"] = TokenFail
    syms["lock"] = TokenLock
    syms["expired"] = TokenExpired
    syms["timer"] = TokenTimer
    syms["timeout"] = TokenTimeout
    syms["itemused"] = TokenItemUsed
    def __init__(self, app, spec, general_spec):
        Module.__init__(self, app, "mg.mmorpg.quest_parser.QuestScriptParser")
        Parsing.Lr.__init__(self, spec)
        self.general_spec = general_spec

    def parse_text(self, text, context):
        parser = ScriptTextParser(self.app(), self.general_spec)
        try:
            try:
                parser.scan(text)
                parser.eoi()
            except Parsing.SyntaxError as e:
                raise ScriptParserError(u"%s: %s" % (context, e))
            except ScriptParser as e:
                raise ScriptParserError(u"%s: %s" % (context, e))
        except ScriptParserResult as e:
            return e.val
        return None