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

from mg import *
from mg.constructor import *
from mg.core.money_classes import *
from mg.core.money import re_valid_code
from mg.core.projects import Project, ProjectList
from mg.core.auth import User, UserList

operations_per_page = 50

class AdminDonate(ConstructorModule):
    def register(self):
        self.rhook("queue-gen.schedule", self.schedule)
        self.rhook("admin-money.donate-admins", self.donate_admins)

    def schedule(self, sched):
        sched.add("admin-money.donate-admins", "0 3 * * *", priority=9)

    def donate_admins(self):
        self.debug("Evaluating game administrators monthly donate")
        objlist = self.int_app().objlist(ProjectList, query_index="published")
        self.debug("Number of games: %d" % len(objlist))
        # gather statistics
        admins = {}
        cnt = 0
        for lstent in objlist:
            cnt += 1
            if (cnt % 1000) == 0:
                self.debug("Processing project %d" % cnt)
            try:
                project = self.int_app().obj(Project, lstent.uuid)
            except ObjectNotFoundException:
                continue
            donate = project.get("monthly_donate", 0)
            if donate > 0:
                try:
                    admins[project.get("owner")] += donate
                except KeyError:
                    admins[project.get("owner")] = donate
        # store admins powers
        self.debug("Loading list of administrators")
        objlist = self.main_app().objlist(UserList, query_index="created")
        self.debug("Number of administrators: %d" % len(objlist))
        cnt = 0
        for lstent in objlist:
            cnt += 1
            if (cnt % 1000) == 0:
                self.debug("Processing user %d" % cnt)
            try:
                user = self.main_app().obj(User, lstent.uuid)
            except ObjectNotFoundException:
                continue
            user.set("monthly_donate", admins.get(user.uuid, 0))
            user.store()

class Money(ConstructorModule):
    def register(self):
        self.rhook("gameinterface.buttons", self.gameinterface_buttons)
        self.rhook("ext-money.index", self.money_index, priv="logged")
        self.rhook("ext-money.operations", self.money_operations, priv="logged")
        self.rhook("xsolla.payment-args", self.payment_args)
        self.rhook("game.dashboard", self.game_dashboard)
        self.rhook("advice-admin-game.dashboard", self.advice_game_dashboard)
        self.rhook("advice-admin-money.index", self.advice_money)
        self.rhook("queue-gen.schedule", self.schedule)
        self.rhook("admin-money.donate-stats", self.donate_stats)
        self.rhook("money-event.credit", self.event_credit)
        self.rhook("money-event.debit", self.event_debit)
        self.rhook("hook-character.money", self.hook_money)

    def schedule(self, sched):
        sched.add("admin-money.donate-stats", "0 1 * * *", priority=10)

    def payment_args(self, args, options):
        character = options.get("character")
        if character:
            args["v1"] = character.name

    def gameinterface_buttons(self, buttons):
        buttons.append({
            "id": "money",
            "href": "/money",
            "target": "main",
            "icon": "money.png",
            "title": self._("Money"),
            "block": "left-menu",
            "order": 7,
        })

    def money_index(self):
        req = self.req()
        character = self.character(req.user())
        money = character.money
        currencies = {}
        self.call("currencies.list", currencies)
        accounts = []
        for currency, currency_info in sorted(currencies.iteritems(), cmp=lambda x, y: cmp(x[1].get("order", 0.0), y[1].get("order", 0.0)) or cmp(x[0], y[0])):
            account = money.account(currency)
            if account:
                balance = nn(account.get("balance"))
                locked = nn(account.get("locked"))
            else:
                balance = 0
                locked = 0
            raccount = {
                "currency": currency_info,
                "balance": balance,
                "balance_currency": self.call("l10n.literal_value", balance, currency_info.get("name_local")),
                "locked": locked,
                "locked_currency": self.call("l10n.literal_value", locked, currency_info.get("name_local")),
            }
            menu = []
            menu.append({"href": "/money/operations/%s" % currency, "html": self._("money///open history")})
            if currency_info.get("real"):
                menu.append({"href": "javascript:void(0)", "onclick": "parent.Xsolla.paystation(); return false", "html": self._("money///buy %s") % currency_info.get("name_plural", "").lower()})
            if menu:
                menu[-1]["lst"] = True
                raccount["menu"] = menu
            accounts.append(raccount)
        vars = {
            "accounts": accounts,
            "Money": self._("Money"),
            "title": self._("Money"),
        }
        self.call("game.response_internal", "money-accounts.html", vars)

    def money_operations(self):
        req = self.req()
        character = self.character(req.user())
        money = character.money
        currencies = {}
        self.call("currencies.list", currencies)
        currency = req.args
        currency_info = currencies.get(currency)
        if not currency_info:
            self.call("web.redirect", "/money")
        vars = {
            "ret": {
                "href": "/money",
                "html": self._("Return"),
            },
            "title": htmlescape(currency_info.get("name_plural")),
        }
        account = money.account(currency)
        self.render_operations(account, vars)
        self.call("game.response_internal", "money-operations.html", vars)

    def render_operations(self, account, vars):
        req = self.req()
        if account:
            page = intz(req.param("page"))
            lst = self.objlist(AccountOperationList, query_index="account", query_equal=account.uuid, query_reversed=True)
            pages = (len(lst) - 1) / operations_per_page + 1
            if pages < 1:
                pages = 1
            if page < 1:
                page = 1
            if page > pages:
                page = pages
            del lst[page * operations_per_page:]
            del lst[0:(page - 1) * operations_per_page]
            lst.load()
            operations = []
            for op in lst:
                description = self.call("money-description.%s" % op.get("description"))
                rop = {
                    "performed": self.call("l10n.time_local", op.get("performed")),
                    "amount": op.get("amount"),
                    "balance": op.get("balance"),
                    "cls": "money-plus" if op.get("balance") >= 0 else "money-minus",
                }
                if op.get("override"):
                    rop["description"] = op.get("override")
                else:
                    rop["description"] = op.get("description")
                    if description:
                        if callable(description["text"]):
                            rop["description"] = description["text"](op.data)
                        else:
                            watchdog = 0
                            while True:
                                watchdog += 1
                                if watchdog >= 100:
                                    break
                                try:
                                    rop["description"] = description["text"].format(**op.data)
                                except KeyError as e:
                                    op.data[e.args[0]] = "{%s}" % e.args[0]
                                else:
                                    break
                if op.get("comment"):
                    rop["description"] = "%s: %s" % (rop["description"], htmlescape(op.get("comment")))
                operations.append(rop)
            vars["operations"] = operations
            if pages > 1:
                url = req.uri()
                vars["pages"] = [{"html": pg, "href": "%s?page=%d" % (url, pg) if pg != page else None} for pg in xrange(1, pages + 1)]
                vars["pages"][-1]["lst"] = True
        vars["Performed"] = self._("moneyop///Performed")
        vars["Amount"] = self._("moneyop///Amount")
        vars["Balance"] = self._("moneyop///Balance")
        vars["Description"] = self._("moneyop///Description")

    def game_dashboard(self, vars):
        vars["IncomeStructure"] = self._("Income structure")
        vars["ForTheLastMonth"] = self._("for the last month")
        vars["LastPayments"] = self._("Last players payments")
        vars["NoData"] = self._("No data")
        # income structure
        lst = self.objlist(PaymentXsollaList, query_index="all", query_start=self.now(-86400 * 30))
        lst.load()
        ranges = {}
        for ent in lst:
            if ent.get("cancelled"):
                continue
            rub = ent.get("amount_rub")
            if not rub:
                continue
            if rub < 300:
                r = "0-299"
            elif rub < 1000:
                r = "300-999"
            elif rub < 10000:
                r = "1000-9999"
            else:
                r = "10000+"
            try:
                ranges[r] += rub
            except KeyError:
                ranges[r] = rub
        if len(ranges):
            income_ranges = []
            for r in ["0-299", "300-999", "1000-9999", "10000+"]:
                income_ranges.append({"text": self._('%s roubl') % r, "amount": int(ranges.get(r, 0))})
            vars["income_ranges"] = income_ranges
        # last payments
        currency = self.call("money.real-currency")
        lst = self.objlist(PaymentXsollaList, query_index="all", query_reversed=True, query_limit=20)
        lst.load()
        rows = []
        for ent in lst:
            amount_rub = '%.2f' % ent.get("amount_rub", 0)
            if ent.get("cancelled"):
                amount_rub = '<strike>%s</strike>' % amount_rub
            rows.append([
                {"html": self.call("l10n.time_local", ent.get("performed"))},
                {"html": self.character(ent.get("user")).html("admin")},
                {"html": self.call("money.price-html", ent.get("sum"), currency), "cls": "td-number"},
                {"html": amount_rub, "cls": "td-number"},
            ])
        vars["last_payments"] = {
            "header": [
                {"html": self._("payment///Performed")},
                {"html": self._("Character")},
                {"html": self._("Amount"), "cls": "td-number"},
                {"html": self._("Income"), "cls": "td-number"},
            ],
            "rows": rows,
        }

    def advice_game_dashboard(self, args, advice):
        if args == "" and self.app().project.get("published"):
            advice.append({"title": self._("Payments structure"), "content": self._("Payments structure chart shows your gross receipt by single payment size. If you see some payment sizes are not very popular it means you should add some offers requiring such payments and promote them to the players"), "order": 5})

    def advice_money(self, hook, args, advice):
        advice.append({"title": self._("Money system documentation"), "content": self._('Detailed description of the currency setup you can read in the <a href="//www.%s/doc/newgame#money" target="_blank">reference manual page</a>.') % self.main_host})

    def donate_stats(self):
        try:
            project = self.app().project
        except AttributeError:
            return
        amount = self.sql_read.selectall("select sum(income_amount-chargebacks_amount) from donate where app=? and period > date_sub(now(), interval 1 month)", self.app().tag)[0][0]
        amount = nn(amount)
        project.set("monthly_donate", amount)
        project.store()

    def event_credit(self, member, amount, currency, description):
        self.money_event(member, amount, currency, description)

    def event_debit(self, member, amount, currency, description):
        self.money_event(member, -amount, currency, description)

    def money_event(self, member, amount, currency, description):
        if member.member_type == "user":
            char = self.character(member.member)
            if not char.valid:
                return
            balance = member.balance(currency)
            self.call("stream.character", char, "characters", "money_changed", amount=amount, balance=balance, currency=currency, description=description)
            self.qevent("money-changed", char=char, amount=amount, balance=balance, currency=currency, description=description)

    def hook_money(self, vars, currency):
        if not re_valid_code.match(currency):
            return ''
        try:
            req = self.req()
        except AttributeError:
            return ''
        money = self.call("money.obj", "user", req.user())
        if not money:
            return ''
        return '<span class="char-money-balance-%s">%s</span>' % (currency, money.balance(currency))
