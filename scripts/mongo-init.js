// MongoDB initialisation script
// Creates the acme_dwh database and a read-only reporting user
db = db.getSiblingDB('acme_dwh');

db.createCollection('assets');
db.createCollection('data_sources');
db.createCollection('time_series');
db.createCollection('ingest_log');

print('Acme DWH collections created.');
