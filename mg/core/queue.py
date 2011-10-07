from mg.core import Module
from mg.core.cass import CassandraObject, CassandraObjectList, ObjectNotFoundException
from concurrence import Tasklet
from concurrence.http import HTTPConnection, HTTPError, HTTPRequest
from stackless import channel
from urllib import urlencode
from uuid import uuid4
import json
import time
import logging
import re
import weakref
import datetime
import calendar

class QueueTask(CassandraObject):
    clsname = "QueueTask"
    indexes = {
        "app_at": [["app"], "at"],
        "at": [[], "at"],
        "app_unique": [["app", "unique"]],
    }

class QueueTaskList(CassandraObjectList):
    objcls = QueueTask

class Schedule(CassandraObject):
    clsname = "Schedule"
    indexes = {
        "updated": [[], "updated"],
    }

    def add(self, hook, at, priority=50):
        self.touch()
        entries = self.data["entries"]
        entries[hook] = {
            "at": at,
            "priority": priority,
        }

    def delete(self, hook):
        self.touch()
        entries = self.data["entries"]
        try:
            del entries[hook]
        except KeyError:
            pass

    def store(self):
        if self.get("entries") and len(self.get("entries")):
            self.set("updated", "%020d" % time.time())
            CassandraObject.store(self)
        else:
            self.remove()

class ScheduleList(CassandraObjectList):
    objcls = Schedule

class Queue(Module):
    def register(self):
        self.rhook("queue.add", self.queue_add)
        self.rhook("int-queue.run", self.queue_run, priv="public")
        self.rhook("queue.schedule", self.queue_schedule)
        self.rhook("objclasses.list", self.objclasses_list)
        self.rhook("app.check", self.check)
        self.rhook("queue.generate", self.queue_generate)

    def objclasses_list(self, objclasses):
        objclasses["QueueTask"] = (QueueTask, QueueTaskList)
        objclasses["Schedule"] = (Schedule, ScheduleList)

    def queue_add(self, hook, args={}, at=None, priority=100, unique=None, retry_on_fail=False, app_tag=None, app_cls=None):
        int_app = self.app().inst.int_app
        with int_app.lock(["queue"]):
            if app_tag is None:
                app_tag = self.app().tag
            if app_cls is None:
                app_cls = self.app().inst.cls
            if at is None:
                at = time.time()
            elif type(at) != int:
                ct = CronTime(at)
                if ct.valid:
                    next = ct.next()
                    if next is None:
                        raise CronError("Invalid cron time")
                    at = calendar.timegm(next.utctimetuple())
                else:
                    raise CronError("Invalid cron time")
            data = {
                "app": app_tag,
                "cls": app_cls,
                "at": "%020d" % at,
                "priority": int(priority),
                "hook": hook,
                "args": args,
            }
            if unique is not None:
                existing = int_app.objlist(QueueTaskList, query_index="app_unique", query_equal="%s-%s" % (app_tag, unique))
                existing.remove()
                data["unique"] = unique
            if retry_on_fail:
                data["retry_on_fail"] = True
            task = int_app.obj(QueueTask, data=data)
            task.store()

    def queue_run(self):
        req = self.req()
        m = re.match(r'(\S+?)\/(\S+)', req.args)
        if not m:
            self.call("web.not_found")
        app_tag, hook = m.group(1, 2)
        args = json.loads(req.param("args"))
        app = self.app().inst.appfactory.get_by_tag(app_tag)
        if app is None:
            self.call("web.not_found")
        if args.get("schedule"):
            del args["schedule"]
            if args.has_key("at"):
                del args["at"]
        app.hooks.call(hook, **args)
        self.call("web.response_json", {"ok": 1})

    def queue_schedule(self, empty=False):
        int_app = self.app().inst.int_app
        app_cls = self.app().inst.cls
        app_tag = self.app().tag
        if empty:
            sched = int_app.obj(Schedule, app_tag, data={
                "cls": app_cls,
                "entries": {},
            })
        else:
            try:
                sched = int_app.obj(Schedule, app_tag)
                sched.set("cls", app_cls)
            except ObjectNotFoundException:
                sched = int_app.obj(Schedule, app_tag, data={
                    "entries": {},
                })
        sched.app = weakref.ref(self.app())
        return sched

    def check(self):
        self.queue_generate()

    def queue_generate(self):
        sched = self.call("queue.schedule", empty=True)
        self.call("queue-gen.schedule", sched)
        self.debug("generated schedule for the project %s: %s", sched.uuid, sched.data["entries"])
        sched.store()
        self.call("cluster.query_director", "/schedule/update/%s" % sched.uuid)

class QueueRunner(Module):
    "This module runs on the Director and controls schedule execution"
    def register(self):
        self.rhook("queue.process", self.queue_process)
        self.rhook("queue.processing", self.queue_processing)
        self.rhook("int-schedule.update", self.schedule_update, priv="public")
        self.processing = set()
        self.processing_uniques = set()
        self.workers = 4
        self.last_check = None

    def check(self):
        self.info("Starting daily check")
        apps = []
        self.call("applications.list", apps)
        for app in apps:
            self.call("queue.add", "app.check", priority=0, app_tag=app["tag"], unique="app-check-%s" % app, app_cls=app["cls"])

    def queue_process(self):
        self.wait_free = channel()
        while True:
            try:
                nd = self.nowdate()
                if nd != self.last_check:
                    self.last_check = nd
                    Tasklet.new(self.check)()
                while self.workers <= 0:
                    self.wait_free.receive()
                tasks = self.objlist(QueueTaskList, query_index="at", query_finish="%020d" % time.time(), query_limit=10)
                tasks.load(silent=True)
                anything_processed = False
                no_workers_shown = set()
                if len(tasks):
                    tasks.sort(cmp=lambda x, y: cmp(x.get("priority"), y.get("priority")), reverse=True)
                    if len(tasks) > self.workers:
                        del tasks[self.workers:]
                    queue_workers = self.call("director.queue_workers")
                    for task in tasks:
                        if task.get("cls"):
                            workers = queue_workers.get(task.get("cls"), None)
                            if workers and len(workers):
                                task.remove()
                                worker = workers.pop(0)
                                workers.append(worker)
                                self.workers = self.workers - 1
                                Tasklet.new(self.queue_run)(task, worker)
                                anything_processed = True
                            else:
                                if not task.get("cls") in no_workers_shown:
                                    self.warning("No workers for class %s. Delaying job" % task.get("cls"))
                                    no_workers_shown.add(task.get("cls"))
                                task.set("priority", task.get("priority") - 1)
                                task.store()
                        else:
                            self.error("Missing cls: %s" % task.data)
                            task.remove()
                if not anything_processed:
                    Tasklet.sleep(3)
            except Exception as e:
                logging.getLogger("mg.core.queue.Queue").exception(e)

    def queue_run(self, task, worker):
        self.processing.add(task.uuid)
        unique = task.get("unique")
        if unique is not None:
            self.processing_uniques.add(unique)
        success = False
        tag = str(task.get("app"))
        try:
            res = self.call("cluster.query_server", worker["host"], worker["port"], "/queue/run/%s/%s" % (tag, str(task.get("hook"))), {
                "args": json.dumps(task.get("args")),
            }, timeout=3600)
            if res.get("error"):
                self.warning("%s.%s(%s) - %s", tag, task.get("hook"), task.get("args"), res)
            success = True
        except HTTPError as e:
            self.error("Error executing task %s: %s" % (task.get("hook"), e))
            main_app = self.main_app()
            if main_app:
                if main_app.hooks.call("project.missing", tag):
                    self.info("Removing missing project %s", tag)
                    self.main_app().hooks.call("project.cleanup", tag)
        except Exception as e:
            self.exception(e)
        self.workers = self.workers + 1
        self.processing.discard(task.uuid)
        if unique is not None:
            self.processing_uniques.discard(unique)
        if self.wait_free.balance < 0:
            self.wait_free.send(None)
        if not success and task.get("retry_on_fail"):
            task.set("at", "%020d" % (time.time() + 5))
            task.set("priority", task.get_int("priority") - 10)
            task = self.obj(QueueTask, data=task.data)
            task.store()
        elif task.get("args").get("schedule"):
            try:
                sched = self.obj(Schedule, task.get("app"))
                entries = sched.get("entries")
            except ObjectNotFoundException:
                entries = {}
            params = entries.get(task.get("hook"))
            if params is not None:
                self.schedule_task(task.get("cls"), task.get("app"), task.get("hook"), params)

    def queue_processing(self):
        return (self.processing, self.processing_uniques, self.workers)

    def schedule_update(self):
        req = self.req()
        app_tag = req.args
        try:
            sched = self.obj(Schedule, app_tag)
            entries = sched.get("entries")
        except ObjectNotFoundException:
            entries = {}
        existing = self.objlist(QueueTaskList, query_index="app_at", query_equal=app_tag)
        existing.load(silent=True)
        existing = dict([(task.get("unique"), task) for task in existing if task.get("args").get("schedule")])
        for hook, params in entries.iteritems():
            existing_params = existing.get(hook)
            if not existing_params:
                self.schedule_task(sched.get("cls"), app_tag, hook, params)
            elif existing_params.get("priority") != params.get("priority") or existing_params.get("args").get("at") != params.get("at"):
                self.schedule_task(sched.get("cls"), app_tag, hook, params)
        for hook, task in existing.iteritems():
            if not entries.get(hook):
                task.remove()
        self.call("web.response_json", {"ok": 1})

    def schedule_task(self, cls, app, hook, params):
        if cls is not None:
            self.call("queue.add", hook, {"schedule": True, "at": params["at"]}, at=params["at"], priority=params["priority"], unique="%s.%s.%s" % (cls, app, hook), retry_on_fail=False, app_tag=app, app_cls=cls)

re_cron_num = re.compile('^\d+$')
re_cron_interval = re.compile('^(\d+)-(\d+)$')
re_cron_step = re.compile('^\*/(\d+)$')

class CronAny(object):
    def check(self, value):
        return True
    def __repr__(self):
        return "CronAny()"

class CronNum(object):
    def __init__(self, value):
        self.value = value
    def check(self, value):
        return value == self.value
    def __repr__(self):
        return "CronNum(%d)" % self.value

class CronInterval(object):
    def __init__(self, min, max):
        self.min = min
        self.max = max
    def check(self, value):
        return value >= self.min and value <= self.max
    def __repr__(self):
        return "CronInterval(%d, %d)" % (self.min, self.max)

class CronStep(object):
    def __init__(self, value):
        self.value = value
    def check(self, value):
        return value % self.value == 0
    def __repr__(self):
        return "CronStep(%d)" % self.value

class CronTime(object):
    def __init__(self, str):
        tokens = str.split(" ")
        self.valid = True
        if len(tokens) != 5:
            self.valid = False
            return
        self.tokens = []
        for token in tokens:
            if token == "*":
                self.tokens.append(CronAny())
                continue
            m = re_cron_num.match(token)
            if m:
                self.tokens.append(CronNum(int(token)))
                continue
            m = re_cron_interval.match(token)
            if m:
                min, max = m.group(1, 2)
                self.tokens.append(CronInterval(int(min), int(max)))
                continue
            m = re_cron_step.match(token)
            if m:
                value = m.group(1)
                if value <= 0:
                    self.valid = False
                    return
                self.tokens.append(CronStep(int(value)))
                continue
            self.valid = False
            return
        
    def __str__(self):
        return str(self.tokens)

    def next(self):
        if not self.valid:
            return None
        tm = datetime.datetime.utcfromtimestamp(time.time() + 60).replace(microsecond=0, second=0)
        done = False
        while not done:
            done = True
            watchdog = 0
            while not self.tokens[0].check(tm.minute):
                done = False
                tm += datetime.timedelta(minutes=1)
                watchdog += 1
                if watchdog > 60:
                    return None
            watchdog = 0
            while not self.tokens[1].check(tm.hour):
                done = False
                tm = (tm + datetime.timedelta(hours=1)).replace(minute=0)
                watchdog += 1
                if watchdog > 24:
                    return None
            watchdog = 0
            while not self.tokens[2].check(tm.day):
                done = False
                tm = (tm + datetime.timedelta(days=1)).replace(minute=0, hour=0)
                watchdog += 1
                if watchdog > 62:
                    return None
            watchdog = 0
            while not self.tokens[3].check(tm.month):
                done = False
                if tm.month == 12:
                    tm = tm.replace(month=1, year=tm.year+1, day=1, minute=0, hour=0)
                else:
                    tm = tm.replace(month=tm.month+1, day=1, minute=0, hour=0)
                watchdog += 1
                if watchdog > 12:
                    return None
            watchdog = 0
            while not self.tokens[4].check(tm.isoweekday() % 7):
                done = False
                tm = (tm + datetime.timedelta(days=1)).replace(minute=0, hour=0)
                watchdog += 1
                if watchdog > 7:
                    return None
        return tm

class CronError(Exception):
    pass
