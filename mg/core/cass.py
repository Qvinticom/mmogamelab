from concurrence.http import HTTPConnection, HTTPRequest
import json
import re
import mg.core.tools
from mg.core.thr import Socket
from thrift.transport import TTransport
from cassandra.Cassandra import Client
from cassandra.ttypes import *
import socket
from mg.core import Module
import logging
from uuid import uuid4
import time

cache_interval = 3600

class CassandraError(Exception):
    "This exception can be raised during database queries"
    pass

class JSONError(CassandraError):
    "JSON or UTF-8 decoding error"
    pass

class ObjectNotFoundException(Exception):
    "CassandraObject not found"
    pass

class Cassandra(object):
    """
    Wrapper around CassandraConnection class. It puts CassandraConnection
    back to the pool on destruction
    """
    def __init__(self, pool, keyspace, mc):
        self.pool = pool
        self.keyspace = keyspace
        self.mc = mc

    def apply_keyspace(self, conn):
        if self.keyspace != conn.actual_keyspace:
            conn.set_keyspace(self.keyspace)

    def describe_keyspaces(self, *args, **kwargs):
        conn = self.pool.cget()
        try:
            return conn.cass.describe_keyspaces(*args, **kwargs)
        finally:
            self.pool.cput(conn)

    def describe_keyspace(self, *args, **kwargs):
        conn = self.pool.cget()
        try:
            return conn.cass.describe_keyspace(*args, **kwargs)
        finally:
            self.pool.cput(conn)

    def system_add_keyspace(self, *args, **kwargs):
        conn = self.pool.cget()
        try:
            return conn.cass.system_add_keyspace(*args, **kwargs)
        finally:
            self.pool.cput(conn)

    def system_drop_keyspace(self, *args, **kwargs):
        conn = self.pool.cget()
        try:
            conn.set_keyspace("system")
            return conn.cass.system_drop_keyspace(*args, **kwargs)
        finally:
            self.pool.cput(conn)

    def system_add_column_family(self, *args, **kwargs):
        conn = self.pool.cget()
        try:
            self.apply_keyspace(conn)
            return conn.cass.system_add_column_family(*args, **kwargs)
        finally:
            self.pool.cput(conn)

    def system_drop_column_family(self, *args, **kwargs):
        conn = self.pool.cget()
        try:
            self.apply_keyspace(conn)
            return conn.cass.system_drop_column_family(*args, **kwargs)
        finally:
            self.pool.cput(conn)

    def insert(self, *args, **kwargs):
        conn = self.pool.cget()
        try:
            self.apply_keyspace(conn)
            return conn.cass.insert(*args, **kwargs)
        finally:
            self.pool.cput(conn)

    def get_slice(self, *args, **kwargs):
        conn = self.pool.cget()
        try:
            self.apply_keyspace(conn)
            return conn.cass.get_slice(*args, **kwargs)
        finally:
            self.pool.cput(conn)

    def multiget_slice(self, *args, **kwargs):
        conn = self.pool.cget()
        try:
            self.apply_keyspace(conn)
            return conn.cass.multiget_slice(*args, **kwargs)
        finally:
            self.pool.cput(conn)

    def batch_mutate(self, *args, **kwargs):
        conn = self.pool.cget()
        try:
            self.apply_keyspace(conn)
            return conn.cass.batch_mutate(*args, **kwargs)
        finally:
            self.pool.cput(conn)

    def insert(self, *args, **kwargs):
        conn = self.pool.cget()
        try:
            self.apply_keyspace(conn)
            return conn.cass.insert(*args, **kwargs)
        finally:
            self.pool.cput(conn)

    def remove(self, *args, **kwargs):
        conn = self.pool.cget()
        try:
            self.apply_keyspace(conn)
            return conn.cass.remove(*args, **kwargs)
        finally:
            self.pool.cput(conn)

    def get(self, *args, **kwargs):
        conn = self.pool.cget()
        try:
            self.apply_keyspace(conn)
            return conn.cass.get(*args, **kwargs)
        finally:
            self.pool.cput(conn)

    def get_count(self, *args, **kwargs):
        conn = self.pool.cget()
        try:
            self.apply_keyspace(conn)
            return conn.cass.get_count(*args, **kwargs)
        finally:
            self.pool.cput(conn)

    def get_range_slices(self, *args, **kwargs):
        conn = self.pool.cget()
        try:
            self.apply_keyspace(conn)
            return conn.cass.get_range_slices(*args, **kwargs)
        finally:
            self.pool.cput(conn)

class CassandraPool(object):
    """
    Handles pool of CassandraConnection objects, allowing get and put operations.
    Connections are created on demand
    """
    def __init__(self, hosts=(("127.0.0.1", 9160),), size=None):
        self.hosts = list(hosts)
        self.connections = []
        self.size = size
        self.allocated = 0
        self.channel = None

    def new_connection(self):
        "Create a new CassandraConnection and connect it"
        connection = CassandraConnection(self.hosts)
        connection.connect()
        self.hosts.append(self.hosts.pop(0))
        return connection

    def cget(self):
        "Get a connection from the pool. If the pool is empty, current tasklet will be blocked"
        # The Pool contains at least one connection
        if len(self.connections) > 0:
            return self.connections.pop(0)

        # There are no connections in the pool, but we may allocate more
        if self.size is None or self.allocated < self.size:
            self.allocated += 1
            connection = self.new_connection()
            return connection

        # We may not allocate more connections. Locking on the channel
        if self.channel is None:
            self.channel = stackless.channel()
        return self.channel.receive()

    def cput(self, connection):
        "Return a connection to the pool"
        # If somebody waits on the channel
        if self.channel is not None and self.channel.balance < 0:
            self.channel.send(connection)
        else:
            self.connections.append(connection)

    def new(self):
        "Put a new connection to the pool"
        self.cput(self.new_connection())

    def dbget(self, keyspace, mc):
        "The same as cget, but returns Cassandra wrapper"
        return Cassandra(self, keyspace, mc)

class CassandraConnection(object):
    "CassandraConnection - interface to Cassandra database engine"
    def __init__(self, hosts=(("127.0.0.1", 9160),)):
        """
        hosts - ((host, port), (host, port), ...)
        """
        object.__init__(self)
        self.hosts = hosts
        self.cass = None
        self.actual_keyspace = None

    def __del__(self):
        self.disconnect()

    def connect(self):
        "Establish connection to the cluster"
        try:
            sock = Socket(self.hosts)
            self.trans = TTransport.TFramedTransport(sock)
            proto = TBinaryProtocol.TBinaryProtocolAccelerated(self.trans)
            self.cass = Client(proto)
            self.trans.open()
            self.actual_keyspace = None
        except:
            self.cass = None
            raise

    def disconnect(self):
        "Disconnect from the cluster"
        if self.cass:
            self.trans.close()
            self.trans = None
            self.cass = None

    def set_keyspace(self, keyspace):
        self.actual_keyspace = keyspace
        self.cass.set_keyspace(keyspace)

class CassandraObject(object):
    """
    An ORM object
    """
    def __init__(self, db, uuid=None, data=None, prefix=""):
        """
        db - Cassandra Object
        uuid - ID of object (None if newly created)
        data - preloaded object data (None is not loaded)
        """
        self.db = db
        self.prefix = prefix
        if uuid is None:
            #self.uuid = re.sub(r'^urn:uuid:', '', uuid4().urn)
            self.uuid = uuid4().hex
            self.new = True
            self.dirty = True
            if data is None:
                self.data = {}
            else:
                self.data = data
        else:
            self.uuid = uuid
            self.dirty = False
            self.new = False
            if data is None:
                self.load()
            else:
                self.data = data

    def indexes(self):
        """
        Returns structure describing object indexes. When an object changes it is reflected in its indexes. Format:
        {
          'name1': [['eqfield1']],                            # where eqfield1=<value1>
          'name2': [['eqfield1', 'eqfield2']],                # where eqfield1=<value1> and eqfield2=<value2>
          'name3': [[], 'ordfield'],                          # where ordfield between <value1> and <value2> order by ordfield
          'name4': [['eqfield1'], 'ordfield'],                # where eqfield1=<value1> and ordfield between <value2> and <value3> order by ordfield
          'name5': [['eqfield1', 'eqfield2'], 'ordfield'],    # where eqfield1=<value1> and eqfield2=<value2> and ordfield between <value3> and <value4> order by ordfield
        }
        """
        return {}

    def load(self):
        """
        Load object from the database
        Raises ObjectNotFoundException
        """
        row_id = self.prefix + self.uuid
        self.data = self.db.mc.get(row_id)
        if self.data == "tomb":
#            print "LOAD(MC) %s %s" % (row_id, self.data)
            raise ObjectNotFoundException(row_id)
        elif self.data is None:
            try:
                col = self.db.get(row_id, ColumnPath("Objects", column="data"), ConsistencyLevel.QUORUM).column
            except NotFoundException:
                raise ObjectNotFoundException(row_id)
            self.data = json.loads(col.value)
            self.db.mc.add(row_id, self.data, cache_interval)
#            print "LOAD(DB) %s %s" % (row_id, self.data)
#        else:
#            print "LOAD(MC) %s %s" % (row_id, self.data)
        self.dirty = False

    def index_values(self):
        ind_values = {}
        for index_name, index in self.indexes().iteritems():
            values = []
            abort = False
            for field in index[0]:
                val = self.data.get(field)
                if val is None:
                    abort = True
                    break;
                values.append(val)
            if not abort:
                col = "id"
                if len(index) > 1:
                    val = self.data.get(index[1])
                    if val is None:
                        abort = True
                    else:
                        col = unicode(val) + "-" + unicode(self.uuid)
                if not abort:
                    row_suffix = ""
                    for val in values:
                        row_suffix = "%s-%s" % (row_suffix, val)
                    ind_values[index_name] = [row_suffix, col]
        return ind_values

    def mutate(self, mutations, clock):
        """
        Returns mapping of row_key => [Mutation, Mutation, ...] if modified
        dirty flag is turned off
        """
        if not self.dirty:
            return
#        print "mutating %s: %s" % (self.uuid, self.data)
        # calculating index mutations
        index_values = self.index_values()
        old_index_values = self.data.get("indexes")
        if old_index_values is None:
            self.data["indexes"] = old_index_values = {}
        for index_name, columns in self.indexes().iteritems():
            key = index_values.get(index_name)
            old_key = old_index_values.get(index_name)
            if old_key != key:
                #print "%s: %s => %s" % (index_name, old_key, key)
                if old_key is not None:
                    mutation = Mutation(deletion=Deletion(predicate=SlicePredicate([old_key[1].encode("utf-8")]), clock=clock))
                    index_row = (self.prefix + index_name + old_key[0]).encode("utf-8")
                    #print "delete: row=%s, column=%s" % (index_row, old_key[1].encode("utf-8"))
                    exists = mutations.get(index_row)
                    if exists:
                        exists["Objects"].append(mutation)
                    else:
                        mutations[index_row] = {"Objects": [mutation]}
                if key is None:
                    del old_index_values[index_name]
                else:
                    old_index_values[index_name] = key
                    mutation = Mutation(ColumnOrSuperColumn(Column(name=key[1].encode("utf-8"), value=self.uuid, clock=clock)))
                    index_row = (self.prefix + index_name + key[0]).encode("utf-8")
                    #print [ index_row, key[1] ]
                    #print "insert: row=%s, column=%s" % (index_row, key[1].encode("utf-8"))
                    exists = mutations.get(index_row)
                    if exists:
                        exists["Objects"].append(mutation)
                    else:
                        mutations[index_row] = {"Objects": [mutation]}
        # mutation of the object itself
        row_id = self.prefix + self.uuid
        mutations[row_id] = {"Objects": [Mutation(ColumnOrSuperColumn(Column(name="data", value=json.dumps(self.data).encode("utf-8"), clock=clock)))]}
        self.db.mc.set(row_id, self.data, cache_interval)
#        print "STORE %s %s" % (row_id, self.data)
        self.dirty = False
        self.new = False

    def store(self):
        """
        Store object in the database
        """
        if not self.dirty:
            return
        clock = Clock(time.time() * 1000)
        mutations = {}
        self.mutate(mutations, clock)
        if len(mutations):
            self.db.batch_mutate(mutations, ConsistencyLevel.QUORUM)

    def remove(self):
        """
        Remove object from the database
        """
        #print "removing %s" % self.uuid
        clock = Clock(time.time() * 1000)
        row_id = self.prefix + self.uuid
        self.db.remove(row_id, ColumnPath("Objects"), clock, ConsistencyLevel.QUORUM)
        self.db.mc.set(row_id, "tomb", cache_interval)
        # removing indexes
        mutations = {}
        old_index_values = self.data.get("indexes")
        if old_index_values is not None:
            for index_name, key in old_index_values.iteritems():
                index_row = (self.prefix + index_name + key[0]).encode("utf-8")
                mutations[index_row] = {"Objects": [Mutation(deletion=Deletion(predicate=SlicePredicate([key[1].encode("utf-8")]), clock=clock))]}
                #print "delete: row=%s, column=%s" % (index_row, key[1].encode("utf-8"))
        if len(mutations):
            self.db.batch_mutate(mutations, ConsistencyLevel.QUORUM)
        self.dirty = False
        self.new = False

    def get(self, key):
        """
        Get data key
        """
        return self.data.get(key)

    def set(self, key, value):
        """
        Set data value
        """
        if type(value) == str:
            value = unicode(value, "utf-8")
        self.data[key] = value
        self.dirty = True

    def delkey(self, key):
        """
        Delete key
        """
        try:
            del self.data[key]
            self.dirty = True
        except KeyError:
            pass

    def get_int(self, key):
        val = self.get(key)
        if val is None:
            return 0
        return int(val)

class CassandraObjectList(object):
    def __init__(self, db, uuids=None, prefix="", cls=CassandraObject, query_index=None, query_equal=None, query_start="", query_finish="", query_limit=100, query_reversed=False):
        """
        To access a list of known uuids:
        lst = CassandraObjectList(db, ["uuid1", "uuid2", ...])

        To query equal index 'name2' => [['eqfield1', 'eqfield2']]:
        lst = CassandraObjectList(db, query_index="name2", query_equal="value1-value2", query_limit=1000)

        To query ordered index 'name5' => [['eqfield1', 'eqfield2'], 'ordfield']:
        lst = CassandraObjectList(db, query_index="name5", query_equal="value1-value2", query_start="OrdFrom", query_finish="OrdTo", query_reversed=True)
        """
        self.db = db
        self._loaded = False
        self.index_row = None
        if uuids is not None:
            self.dict = [cls(db, uuid, {}, prefix=prefix) for uuid in uuids]
        elif query_index is not None:
            index_row = prefix + query_index
            if query_equal is not None:
                index_row = index_row + "-" + query_equal
            if type(index_row) == unicode:
                index_row = index_row.encode("utf-8")
#           print "search index row: %s" % index_row
            d = self.db.get_slice(index_row, ColumnParent(column_family="Objects"), SlicePredicate(slice_range=SliceRange(start=query_start, finish=query_finish, reversed=query_reversed, count=query_limit)), ConsistencyLevel.QUORUM)
#           print "loaded index:"
#           for cosc in d:
#               print cosc.column.name
            self.index_row = index_row
            self.index_data = d
            self.dict = [cls(db, col.column.value, {}, prefix=prefix) for col in d]
        else:
            raise RuntimeError("Invalid usage of CassandraObjectList")

    def load(self, silent=False):
        if len(self.dict) > 0:
            row_ids = [(obj.prefix + obj.uuid) for obj in self.dict]
            mc_d = self.db.mc.get_multi(row_ids)
            row_ids = [id for id in row_ids if mc_d.get(id) is None]
            db_d = self.db.multiget_slice(row_ids, ColumnParent(column_family="Objects"), SlicePredicate(column_names=["data"]), ConsistencyLevel.QUORUM) if len(row_ids) else {}
            recovered = False
            for obj in self.dict:
                obj.valid = True
                row_id = obj.prefix + obj.uuid
                data = mc_d.get(row_id)
                if data is not None:
#                    print "LOAD(MC) %s %s" % (obj.uuid, data)
                    if data == "tomb":
                        if silent:
                            if self.index_row is not None:
                                mutations = []
                                clock = None
                                for col in self.index_data:
                                    if col.column.value == obj.uuid:
                                        obj.valid = False
                                        recovered = True
                                        #print "read recovery. removing column %s from index row %s" % (col.column.name, self.index_row)
                                        if clock is None:
                                            clock = Clock(time.time() * 1000)
                                        mutations.append(Mutation(deletion=Deletion(predicate=SlicePredicate([col.column.name]), clock=clock)))
                                        break
                                if len(mutations):
                                    self.db.batch_mutate({self.index_row: {"Objects": mutations}}, ConsistencyLevel.QUORUM)
                        else:
                            raise ObjectNotFoundException("UUID %s (prefix %s) not found" % (obj.uuid, obj.prefix))
                    else:
                        obj.data = data
                        obj.dirty = False
                else:
                    cols = db_d[row_id]
                    if len(cols) > 0:
                        obj.data = json.loads(cols[0].column.value)
                        obj.dirty = False
                        self.db.mc.add(row_id, obj.data, cache_interval)
#                        print "LOAD(DB) %s %s" % (obj.uuid, obj.data)
                    elif silent:
                        if self.index_row is not None:
                            mutations = []
                            clock = None
                            for col in self.index_data:
                                if col.column.value == obj.uuid:
                                    obj.valid = False
                                    recovered = True
                                    #print "read recovery. removing column %s from index row %s" % (col.column.name, self.index_row)
                                    if clock is None:
                                        clock = Clock(time.time() * 1000)
                                    mutations.append(Mutation(deletion=Deletion(predicate=SlicePredicate([col.column.name]), clock=clock)))
                                    break
                            if len(mutations):
                                self.db.batch_mutate({self.index_row: {"Objects": mutations}}, ConsistencyLevel.QUORUM)
                    else:
                        raise ObjectNotFoundException("UUID %s (prefix %s) not found" % (obj.uuid, obj.prefix))
            if recovered:
                self.dict = [obj for obj in self.dict if obj.valid]
        self._loaded = True

    def _load_if_not_yet(self, silent=False):
        if not self._loaded:
            self.load(silent);

    def store(self):
        self._load_if_not_yet()
        if len(self.dict) > 0:
            mutations = {}
            clock = None
            for obj in self.dict:
                if obj.dirty:
                    if clock is None:
                        clock = Clock(time.time() * 1000)
                    obj.mutate(mutations, clock)
            if len(mutations) > 0:
                #print "applying mutations: %s" % mutations
                self.db.batch_mutate(mutations, ConsistencyLevel.QUORUM)

    def remove(self):
        self._load_if_not_yet(True)
        if len(self.dict) > 0:
            clock = Clock(time.time() * 1000)
            mutations = {}
            for obj in self.dict:
                old_index_values = obj.data.get("indexes")
                if old_index_values is not None:
                    for index_name, key in old_index_values.iteritems():
                        index_row = (obj.prefix + index_name + key[0]).encode("utf-8")
                        m = mutations.get(index_row)
                        mutation = Mutation(deletion=Deletion(predicate=SlicePredicate([key[1].encode("utf-8")]), clock=clock))
                        if m is None:
                            mutations[index_row] = {"Objects": [mutation]}
                        else:
                            m["Objects"].append(mutation)
                row_id = obj.prefix + obj.uuid
                obj.db.remove(row_id, ColumnPath("Objects"), clock, ConsistencyLevel.QUORUM)
                obj.db.mc.set(row_id, "tomb", cache_interval)
                obj.dirty = False
                obj.new = False
            # removing indexes
            #print "remove mutations: %s" % mutations
            if len(mutations):
                self.db.batch_mutate(mutations, ConsistencyLevel.QUORUM)

    def __len__(self):
        return self.dict.__len__()

    def __getitem__(self, key):
        return self.dict.__getitem__(key)

    def __setitem__(self, key, value):
        return self.dict.__setitem__(key, value)

    def __delitem__(self, key):
        return self.dict.__delitem__(key)

    def __iter__(self):
        return self.dict.__iter__()

    def __reversed__(self):
        return self.dict.__reversed__()

    def __contains__(self, item):
        return self.dict.__contains__(item)

    def __getslice__(self, i, j):
        return self.dict.__getslice__(i, j)

    def __setslice__(self, i, j, sequence):
        return self.dict.__setslice__(i, j, sequence)

    def __delslice__(self, i, j):
        return self.dict.__delslice__(i, j)

    def data(self):
        res = []
        for d in self.dict:
            ent = d.data.copy()
            ent["uuid"] = d.uuid
            res.append(ent)
        return res

    def __str__(self):
        return str([obj.uuid for obj in self.dict])