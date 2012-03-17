import os
import re
import json
import time
import copy
import random
import signal
import shutil
import socket
import httplib
import subprocess

def block_path(source_port, dest_port):
	assert "resunder" in subprocess.check_output(["ps", "-A"])
	conn = socket.create_connection(("localhost", 46594))
	conn.send("block %s %s" % (str(source_port), str(dest_port)))
	conn.close()

def unblock_path(source_port, dest_port):
	assert "resunder" in subprocess.check_output(["ps", "-A"])
	conn = socket.create_connection(("localhost", 46594))
	conn.send("unblock %s %s" % (str(source_port), str(dest_port)))
	conn.close()

def validate_uuid(json_uuid):
	assert isinstance(json_uuid, str) or isinstance(json_uuid, unicode)
	assert json_uuid.count("-") == 4
	assert len(json_uuid) == 36
	return json_uuid

def is_uuid(json_uuid):
	try:
		validate_uuid(json_uuid)
		return True
	except AssertionError:
		return False

class InvalidServerError(StandardError):
	def __str__(self):
		return "No information about this server is available, server was probably added to the cluster elsewhere"

class ServerExistsError(StandardError):
	def __str__(self):
		return "Attempt to add a server to a cluster where the uuid already exists"

class BadClusterData(StandardError):
	def __init__(self, expected, actual):
		self.expected = expected
		self.actual = actual
	def __str__(self):
		return "Cluster is inconsistent between nodes\nexpected: " + str(self.expected) + "\nactual: " + str(self.actual)

class BadServerResponse(StandardError):
	def __init__(self, status, reason):
		self.status = status
		self.reason = reason
	def __str__(self):
		return "Server returned error code: %d %s" % (self.status, self.reason)

class Datacenter(object):
	def __init__(self, uuid, json_data):
		self.uuid = uuid
		self.name = json_data["name"]

	def check(self, data):
		return data == self.to_json()

	def to_json(self):
		return { unicode("name"): self.name }

	def __str__(self):
		return "Datacenter(name:%s)" % (self.name)

class Blueprint(object):
	def __init__(self, json_data):
		self.peers_roles = json_data["peers_roles"]

	def to_json(self):
		return { unicode("peers_roles"): self.peers_roles }

	def __str__(self):
		return "Blueprint()"

class Namespace(object):
	def __init__(self, uuid, json_data):
		self.uuid = validate_uuid(uuid)
		self.blueprint = Blueprint(json_data["blueprint"])
		self.primary_uuid = validate_uuid(json_data["primary_uuid"])
		self.replica_affinities = json_data["replica_affinities"]
		self.shards = json_data["shards"]
		self.name = json_data["name"]

	def check(self, data):
		return data == self.to_json()

	def to_json(self):
		return { unicode("blueprint"): self.blueprint.to_json(), unicode("name"): self.name, unicode("primary_uuid"): self.primary_uuid, unicode("replica_affinities"): self.replica_affinities, unicode("shards"): self.shards }

	def __str__(self):
		affinities = ""
		if len(self.replica_affinities) == 0:
			affinities = "None, "
		else:
			for i in self.replica_affinities.iteritems():
				affinities += i[0] + "=" + str(i[1]) + ", "
		return "Namespace(name:%s, primary:%s, affinities:%sblueprint:NYI)" % (self.name, self.primary_uuid, affinities)

class DummyNamespace(Namespace):
	def __init__(self, uuid, json_data):
		Namespace.__init__(self, uuid, json_data)

	def __str__(self):
		return "Dummy" + Namespace.__str__(self)

class MemcachedNamespace(Namespace):
	def __init__(self, uuid, json_data):
		Namespace.__init__(self, uuid, json_data)

	def __str__(self):
		return "Memcached" + Namespace.__str__(self)

class Server(object):
	def __init__(self, serv_host, serv_port):
		self.host = serv_host
		self.cluster_port = serv_port
		self.http_port = serv_port + 1000
		self.uuid = validate_uuid(self.do_query("GET", "/ajax/me"))
		serv_info = self.do_query("GET", "/ajax/machines/" + self.uuid)
		self.datacenter_uuid = serv_info["datacenter_uuid"]
		self.name = serv_info["name"]

	def check(self, data):
		# Do not check DummyServer objects
		if type(self) is DummyServer:
			return True
		return data == self.to_json()

	def to_json(self):
		return { unicode("datacenter_uuid"): self.datacenter_uuid, unicode("name"): self.name }

	def do_query(self, method, route, payload = None):
		conn = httplib.HTTPConnection(self.host, self.http_port)
		conn.connect()
		if payload is not None:
			conn.request(method, route, json.dumps(payload))
		else:
			conn.request(method, route)
		response = conn.getresponse()
		if response.status == 200:
			return json.loads(response.read())
		else:
			raise BadServerResponse(response.status, response.reason)

	def __str__(self):
		return "Server(%s:%s, name:%s, datacenter:%s)" % (self.host, self.cluster_port, self.name, self.datacenter_uuid)

class DummyServer(Server):
	def __init__(self, uuid, dummy_data):
		self.uuid = uuid

	def do_query(self, method, route, payload = None):
		raise InvalidServer()

	def __str__(self):
		return "DummyServer()"

class ExternalServer(Server):
	def __init__(self, serv_host, serv_port):
		Server.__init__(self, serv_host, serv_port)

	def __str__(self):
		return "External" + Server.__str__(self)

class InternalServer(Server):
	def __init__(self, serv_port, local_cluster_port, cluster_host = None, cluster_port = None):
		# Make a temporary file for the database
		self.db_dir = "/tmp/rethinkdb-port-" + str(serv_port)
		assert not os.path.exists(self.db_dir)

		# Otherwise, we need to create a new server
		if cluster_port is None:
			self.args = ["../../build/debug/rethinkdb", "--directory=" + self.db_dir, "--port=" + str(serv_port), "--client-port=" + str(local_cluster_port)]
		else:
			self.args = ["../../build/debug/rethinkdb", "--directory=" + self.db_dir, "--port=" + str(serv_port), "--client-port=" + str(local_cluster_port), "--join=" + str(cluster_host) + ":" + str(cluster_port)]

		self.local_cluster_port = local_cluster_port

		print self.args
		self.instance = subprocess.Popen(self.args, 0, None, None, subprocess.PIPE)
		time.sleep(0.2)
		Server.__init__(self, socket.gethostname(), serv_port)
		self.running = True

	def kill(self):
		assert self.running
		self.instance.send_signal(signal.SIGINT)
		self.instance.wait()
		self.running = False

	def recover(self):
		assert not self.running
		self.instance = subprocess.Popen(self.args, 0, None, None, subprocess.PIPE)
		self.running = True

	def __del__(self):
		self.instance.send_signal(signal.SIGINT)
		self.instance.wait()
		shutil.rmtree(self.db_dir)

	def __str__(self):
		return "Internal" + Server.__str__(self) + ", args:" + str(self.args)

class Cluster(object):
	def __init__(self):
		try:
			self.base_port = os.environ["RETHINKDB_BASE_PORT"]
		except KeyError:
			self.base_port = random.randint(20000, 60000)
			print "Warning: environment variable 'RETHINKDB_BASE_PORT' not set, using random base port: " + str(self.base_port)

		self.server_instances = 0
		self.machines = { }
		self.datacenters = { }
		self.dummy_namespaces = { }
		self.memcached_namespaces = { }

	def __str__(self):
		retval = "Machines:"
		for i in self.machines.iterkeys():
			retval += "\n%s: %s" % (i, self.machines[i])
		retval += "\nDatacenters:"
		for i in self.datacenters.iterkeys():
			retval += "\n%s: %s" % (i, self.datacenters[i])
		retval += "\nNamespaces:"
		for i in self.dummy_namespaces.iterkeys():
			retval += "\n%s: %s" % (i, self.dummy_namespaces[i])
		for i in self.memcached_namespaces.iterkeys():
			retval += "\n%s: %s" % (i, self.memcached_namespaces[i])
		return retval

	def print_machines(self):
		for i in self.machines.iterkeys():
			print "%s: %s" % (i, self.machines[i])

	def print_namespaces(self):
		for i in self.dummy_namespaces.iterkeys():
			print "%s: %s" % (i, self.dummy_namespaces[i])
		for i in self.memcached_namespaces.iterkeys():
			print "%s: %s" % (i, self.memcached_namespaces[i])

	def print_datacenters(self):
		for i in self.datacenters.iterkeys():
			print "%s: %s" % (i, self.datacenters[i])

	def _get_server_for_command(self, servid = None):
		if servid is None:
			for serv in self.machines.itervalues():
				if type(serv) is not DummyServer:
					return serv
		else:
			return self.machines[servid]

	# Add a machine to the cluster by starting a server instance locally
	def add_machine(self):
		if self.server_instances is 0:
			serv = InternalServer(self.base_port, self.base_port - 1) # First server in cluster shouldn't connect to anyone
		else:
			serv = InternalServer(self.base_port + self.server_instances, self.base_port - self.server_instances - 1, socket.gethostname(), self.base_port)
		self.machines[serv.uuid] = serv
		self.server_instances += 1
		time.sleep(0.2)
		self.update_cluster_data()
		return serv

	# Add a machine that was added elsewhere - there should already be a dummy server instance as a placeholder
	def add_existing_machine(self, serv):
		assert isinstance(serv, Server)
		old = self.machines.get(serv.uuid)
		if old is not None:
			# If the old uuid is a dummy server, replace it
			if not isinstance(old, DummyServer):
				raise ServerExistsError()
		self.machines[serv.uuid] = serv
		self.server_instances += 1
		self.update_cluster_data()
		return serv

	def add_datacenter(self, servid = None):
		info = self._get_server_for_command(servid).do_query("POST", "/ajax/datacenters/new", { })
		time.sleep(0.2) # Give some time for changes to hit the rest of the cluster
		assert len(info) is 1
		info = next(info.iteritems())
		datacenter = Datacenter(info[0], info[1])
		self.datacenters[datacenter.uuid] = datacenter
		self.update_cluster_data()
		return datacenter

	def move_server_to_datacenter(self, serv, datacenter, servid = None):
		if type(serv) is str or type(serv) is unicode:
			serv = self.machines[serv]
		if type(datacenter) is str or type(datacenter) is unicode:
			datacenter = self.datacenters[datacenter]
		assert self.machines[serv.uuid] is serv
		assert self.datacenters[datacenter.uuid] is datacenter
		if type(serv) is not DummyServer:
			serv.datacenter_uuid = datacenter.uuid
		self._get_server_for_command(servid).do_query("POST", "/ajax/machines/" + serv.uuid + "/datacenter_uuid", datacenter.uuid)
		time.sleep(0.2) # Give some time for changes to hit the rest of the cluster
		self.update_cluster_data()
		return datacenter

	# Add a dummy namespace through the given uuid of a machine in the cluster
	def add_dummy_namespace(self, servid = None):
		info = self._get_server_for_command(servid).do_query("POST", "/ajax/dummy_namespaces/new", { })
		time.sleep(0.2) # Give some time for changes to hit the rest of the cluster
		assert len(info) is 1
		info = next(info.iteritems())
		namespace = DummyNamespace(info[0], info[1])
		self.dummy_namespaces[namespace.uuid] = namespace
		self.update_cluster_data()
		return namespace

	def move_namespace_to_datacenter(self, namespace, primary, servid = None):
		if type(namespace) is str or type(namespace) is unicode:
			if namespace in self.dummy_namespaces:
				namespace = self.dummy_namespaces[namespace]
			elif namespace in self.memcached_namespaces:
				namespace = self.memcached_namespaces[namespace]
			else:
				assert False
		if type(primary) is str or type(primary) is unicode:
			primary = self.datacenters[primary]
		assert self.datacenters[primary.uuid] is primary
		namespace.primary_uuid = primary.uuid
		if type(namespace) == MemcachedNamespace:
			assert self.memcached_namespaces[namespace.uuid] is namespace
			self._get_server_for_command(servid).do_query("POST", "/ajax/memcached_namespaces/" + namespace.uuid, namespace.to_json())
		elif type(namespace) == DummyNamespace:
			assert self.dummy_namespaces[namespace.uuid] is namespace
			self._get_server_for_command(servid).do_query("POST", "/ajax/dummy_namespaces/" + namespace.uuid, namespace.to_json())
		time.sleep(0.2) # Give some time for the changes to hit the rest of the cluster
		self.update_cluster_data()
		return namespace

	def set_namespace_affinities(self, namespace, affinities = { }, servid = None):
		aff_dict = { }
		for i in affinities.iterkeys():
			assert i.uuid in self.datacenters
			aff_dict[i.uuid] = affinities[i]
		namespace.replica_affinities = aff_dict
		if type(namespace) == MemcachedNamespace:
			assert self.memcached_namespaces[namespace.uuid] is namespace
			self._get_server_for_command(servid).do_query("POST", "/ajax/memcached_namespaces/" + namespace.uuid, namespace.to_json())
		elif type(namespace) == DummyNamespace:
			assert self.dummy_namespaces[namespace.uuid] is namespace
			self._get_server_for_command(servid).do_query("POST", "/ajax/dummy_namespaces/" + namespace.uuid, namespace.to_json())
		time.sleep(0.2) # Give some time for the changes to hit the rest of the cluster
		self.update_cluster_data()
		return namespace

	# Add a memcached namespace through the given uuid of a machine in the cluster
	def add_memcached_namespace(self, servid = None):
		info = self._get_server_for_command(servid).do_query("POST", "/ajax/memcached_namespaces/new", { })
		time.sleep(0.2) # Give some time for the changes to hit the rest of the cluster
		assert len(info) is 1
		info = next(info.iteritems())
		namespace = MemcachedNamespace(info[0], info[1])
		self.memcached_namespaces[namespace.uuid] = namespace
		self.update_cluster_data()
		return namespace

	def _pull_cluster_data(self, cluster_data, local_data, data_type):
		num_uuids = 0
		for uuid in cluster_data.iterkeys():
			# There are also aliases in the list, ignore things that don't match a uuid
			if is_uuid(uuid):
				num_uuids += 1
				if uuid not in local_data:
					local_data[uuid] = data_type(uuid, cluster_data[uuid])
		assert num_uuids == len(local_data)

	# Get the list of machines/namespaces from the cluster, verify that it is consistent across each machine
	def _verify_consistent_cluster(self):
		expected = self._get_server_for_command().do_query("GET", "/ajax/")
		# Filter out the "me" value - it will be different on each machine
		assert expected.pop("me") is not None
		for i in self.machines.iterkeys():
			if type(self.machines[i]) is DummyServer: # Don't try to query a server we don't know anything about
				continue

			actual = self.machines[i].do_query("GET", "/ajax/")
			assert actual.pop("me") == self.machines[i].uuid
			if actual != expected:
				raise BadClusterData(expected, actual)
		return expected

	def _verify_cluster_data_chunk(self, local, remote):
		for i in local.iteritems():
			assert i[1].check(remote[i[0]])

	# Check the data from the server against our data
	def _verify_cluster_data(self, data):
		self._verify_cluster_data_chunk(self.machines, data["machines"])
		self._verify_cluster_data_chunk(self.datacenters, data["datacenters"])
		self._verify_cluster_data_chunk(self.dummy_namespaces, data["dummy_namespaces"])
		self._verify_cluster_data_chunk(self.memcached_namespaces, data["memcached_namespaces"])

	def update_cluster_data(self):
		data = self._verify_consistent_cluster()
		self._pull_cluster_data(data["machines"], self.machines, DummyServer)
		self._pull_cluster_data(data["datacenters"], self.datacenters, Datacenter)
		self._pull_cluster_data(data["dummy_namespaces"], self.dummy_namespaces, DummyNamespace)
		self._pull_cluster_data(data["memcached_namespaces"], self.memcached_namespaces, MemcachedNamespace)
		self._verify_cluster_data(data)
		return data

class ExternalCluster(Cluster):
	def __init__(self, serv_list):
		Cluster.__init__(self)
		# Save servers in the cluster by uuid
		for serv in serv_list:
			self.machines[serv.uuid] = serv
			self.server_instances += 1

		# Pull any existing cluster information
		self.update_cluster_data()

class InternalCluster(Cluster):
	# datacenters - array of counts - number of machines to put in each datacenter
	# affinities - array of arrays of tuples - first array - one item per namespace type (dummy and memcached in that order)
	#                                          second array - one item per namespace to create
	#                                          tuple - first value is the index of the primary datacenter, second value is
	#                                              an array with one item per datacenter, an integer value for the affinity towards that datacenter
	def __init__(self, datacenters = [ ], affinities = [ ]):
		assert len(affinities) <= 2 # only two namespace types at the moment - dummy and memcached
		for i in affinities:
			for j in i:
				assert j[0] < len(datacenters) # make sure the primary datacenter id doesn't overflow
				assert len(j[1]) == len(datacenters) or len(j[1]) == 0 # namespace affinities must define values for each datacenter or no affinities

		Cluster.__init__(self)
		self.blocked_ports = set()
		self.other_clusters = set()

		while len(self.machines) < sum(datacenters):
			self.add_machine()
		assert len(self.machines) == sum(datacenters)

		while len(self.datacenters) < len(datacenters):
			self.add_datacenter()
		assert len(self.datacenters) == len(datacenters)

		# Balance servers across datacenters as requested
		server_iter = self.machines.itervalues()
		datacenter_list = self.datacenters.values()
		assert len(self.machines) == sum(datacenters)
		for i in range(len(datacenters)):
			for j in range(datacenters[i]):
				self.move_server_to_datacenter(next(server_iter), datacenter_list[i])

		datacenter_list = self.datacenters.values()
		# Initialize dummy namespaces with given affinities
		if len(affinities) >= 1:
			affinity_offset = 0
			for namespace in self.dummy_namespaces.itervalues():
				self._initialize_namespace(namespace, datacenter_list, affinities[0][affinity_offset])
				affinity_offset += 1
			while len(self.dummy_namespaces) < len(affinities[0]):
				self._initialize_namespace(self.add_dummy_namespace(), datacenter_list, affinities[0][affinity_offset])
				affinity_offset += 1
			assert affinity_offset == len(affinities[0])

		# Initialize memcached namespaces with given affinities
		if len(affinities) >= 2:
			affinity_offset = 0
			for namespace in self.memcached_namespaces.itervalues():
				self._initialize_namespace(namespace, datacenter_list, affinities[1][affinity_offset])
				affinity_offset += 1
			while len(self.memcached_namespaces) < len(affinities[1]):
				self._initialize_namespace(self.add_memcached_namespace(), datacenter_list, affinities[1][affinity_offset])
				affinity_offset += 1
			assert affinity_offset == len(affinities[1])

	def __del__(self):
		# Clean up any remaining blocked paths
		for m in self.machines:
			for dest_port in self.blocked_ports:
				unblock_path(m.local_cluster_port, dest_port)

	def _initialize_namespace(self, namespace, datacenter_list, affinity):
		primary, aff_data = affinity
		if len(aff_data) > 0:
			a = { }
			for d in range(len(datacenter_list)):
				a[datacenter_list[d]] = aff_data[d]
			self.set_namespace_affinities(namespace, a)
		self.move_namespace_to_datacenter(namespace, datacenter_list[primary])

	# Sets up iptables rules to isolate a set of machines from the cluster, constructs a new cluster object with the selected machines
	# This won't block any DummyServers in your cluster (ExternalServers that have not been initialized by the user)
	def split(self, machines):
		if type(machines) is int:
			# Pick n arbitrary machines
			n = machines
			machines = [ ]
			machines_list = self.machines.values()
			machines_index = 0
			for i in range(n):
				while type(machines_list[machines_index]) is DummyServer:
					machines_index += 1
				machines.append(machines_list[machines_index])
				machines_index += 1

		for m in machines:
			assert m.uuid in self.machines
			assert type(m) is not DummyServer

		# Create a new cluster and copy all cluster data
		new_cluster = InternalCluster([ ], [ ])
		new_cluster.blocked_ports = copy.deepcopy(self.blocked_ports)
		new_cluster.datacenters = copy.deepcopy(self.datacenters)
		new_cluster.dummy_namespaces = copy.deepcopy(self.dummy_namespaces)
		new_cluster.memcached_namespaces = copy.deepcopy(self.memcached_namespaces)

		ports_to_block_self = set()
		ports_to_block_new = set()

		# Move selected machines into the new cluster
		for m in machines:
			new_cluster.machines[m.uuid] = m
			self.machines.pop(m.uuid)
			ports_to_block_self.add(m.cluster_port)

		for m in self.machines.values():
			if type(m) is not DummyServer:
				ports_to_block_new.add(m.cluster_port)

		# Block ports from this cluster to the new cluster
		for m in self.machines.values():
			if type(m) is not DummyServer:
				for p in ports_to_block_self:
					block_path(m.local_cluster_port, p)

		# Block ports from the new cluster to this cluster
		for m in new_cluster.machines.values():
			if type(m) is not DummyServer:
				for p in ports_to_block_new:
					block_path(m.local_cluster_port, p)

		self.blocked_ports = self.blocked_ports | ports_to_block_self
		new_cluster.blocked_ports = new_cluster.blocked_ports | ports_to_block_new

		# Make sure all other clusters know about the new cluster
		for c in self.other_clusters:
			c.other_clusters.add(new_cluster)

		new_cluster.other_clusters = copy.copy(self.other_clusters)
		new_cluster.other_clusters.add(self)
		self.other_clusters.add(new_cluster)

		# This should fill in missing machines with DummyServers
		self.update_cluster_data()
		new_cluster.update_cluster_data()

		return new_cluster

	# Removes the iptables blocked ports to join this cluster with the cluster passed as an argument, which is then deleted
	# These two clusters must be pieces of the same original cluster
	def join(self, other):
		assert other in self.other_clusters
		assert self in other.other_clusters

		# Remove blocks between the clusters
		for m in self.machines.values():
			if type(m) is not DummyServer:
				for n in other.machines.values():
					if type(n) is not DummyServer:
						unblock_path(m.local_cluster_port, n.cluster_port)
						unblock_path(n.local_cluster_port, m.cluster_port)

		for m in self.machines.values():
			if type(m) is not DummyServer:
				other.blocked_ports.remove(m.cluster_port)
		for m in other.machines.values():
			if type(m) is not DummyServer:
				self.blocked_ports.remove(m.cluster_port)
				self.machines[m.uuid] = m

		# Add items from other cluster into this cluster
		self.datacenters.update(other.datacenters)
		self.dummy_namespaces.update(other.dummy_namespaces)
		self.memcached_namespaces.update(other.memcached_namespaces)

		# Update other_clusters in this cluster
		self.other_clusters.remove(other)
		other.other_clusters.remove(self)

		# Update other_clusters in all remaining clusters
		for c in self.other_clusters:
			c.other_clusters.remove(other)

		# Do some sanity checks to make sure everything is working
		assert self.blocked_ports == other.blocked_ports
		assert self.other_clusters == other.other_clusters
		# Clear out other cluster as it is no longer valid
		other.machines = { }
		other.datacenters = { }
		other.dummy_namespaces = { }
		other.memcached_namespaces = { }
		other.blocked_ports = set()
		other.other_cluster = set()

		# Give some time for the cluster to update internally, then pull the cluster data
		time.sleep(1)
		self.update_cluster_data()

	def _notify_of_new_cluster_port(self, port):
		self.blocked_ports.add(port)
		for m in self.machines.itervalues():
			if type(m) is not DummyServer:
				block_path(m.cluster_port, port)

	def add_machine(self):
		# Block the new machine's port across all pieces of the cluster before we actually run the server
		new_local_cluster_port = self.base_port - self.server_instances - 1
		new_cluster_port = self.base_port + self.server_instances
		for c in self.other_clusters:
			c._notify_of_new_cluster_port(new_cluster_port)
		for p in self.blocked_ports:
			block_path(new_local_cluster_port, p)
		return Cluster.add_machine(self)

	def add_existing_machine(self, machine):
		assert len(self.other_clusters) != 0 # Cannot have a split cluster with externally-added machines
		return Cluster.add_existing_machine(self)

	# Kills the rethinkdb process with SIGINT, leaves the Server object so it may be restarted with the same data
	def kill_machines(self, machines):
		for m in machines:
			assert m.uuid in self.machines

		for m in machines:
			m.kill()

	# Brings machines back into the cluster, by restarting the killed process, or unblocking ports
	def recover_machines(self, machines):
		for m in machines:
			assert m.uuid in self.machines

		for m in machines:
			m.recover()

