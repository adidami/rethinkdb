rethinkdb = require('./ast')
net = require('./net')
protobuf = require('./protobuf')
errors = require('./errors')

# Add connect from net module
rethinkdb.connect = net.connect

# Add protobuf_implementation from the protobuf module
rethinkdb.protobuf_implementation = protobuf.protobuf_implementation

rethinkdb.Error = error

module.exports = rethinkdb
