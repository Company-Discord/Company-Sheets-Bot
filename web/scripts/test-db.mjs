// Ephemeral loopback-only PostgreSQL-compatible database for integration tests.
// It never loads .env or connects to the company database.
import {PGlite} from '@electric-sql/pglite';
import {PGLiteSocketServer} from '@electric-sql/pglite-socket';
const db = await PGlite.create();
const server = new PGLiteSocketServer({db,host:'127.0.0.1',port:55432,maxConnections:4});
await server.start();
console.log('Test database ready: postgresql://postgres:postgres@127.0.0.1:55432/postgres?sslmode=disable');
async function stop(){await server.stop();await db.close();process.exit(0)}
process.on('SIGINT',stop);process.on('SIGTERM',stop);
