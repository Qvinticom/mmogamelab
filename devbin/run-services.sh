#!/bin/sh
/etc/init.d/mysql start
#/etc/init.d/realplexor start
/etc/init.d/memcached start
/etc/init.d/nginx start
/etc/init.d/cassandra start