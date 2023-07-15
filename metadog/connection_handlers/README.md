# Connection handlers

There are currently 3 connection handlers, that handle connections to file- and object-storage systems. The configuration is slightly different for each.


## SFTP

**TBD**

configuration:
- `path`: optional path on the SFTP server to scan. Defaults to home/current directory (`./`)
- `get_schemas`: bool specifying whether to read files to infer schema.
- `connection`: Dictionary containing `host`, `user`, `password`, and `port`.

<!--
For sources of type SFTP, the configuration consists of an optional `path` key to specify the folder you want to scan, an optional `get_schemas` key specifying wether or not to scan the files in the bucket and infer schema (true/false flag), and a `connection` key containing the `host`, `username`, `password` and `port`.
-->

## S3

configuration:
- `bucket`: S3 bucket and optional prefix for subfolder. Do not include the `s3://` prefix.
- `get_schemas`: bool specifying whether to read files to infer schema.
- `connection`: Dictionary containing the connection options. These are passed to fsspec, and depends on how you want to authenticate. For publically open buckets, you can specify `anon: true`. 


## Azure Storage

Configuration:
- `path`: Container name and optional subfolder path to scan.
- `get_schemas`: bool specifying whether to read files to infer schema.
- `connection`: Dictionary containing the connection options. These are passed to fsspec, and depends on how you want to authenticate. Regardless of authentication, it must contain the key `account_name` to specify the name of the storage account. For authenticating with a storage account key, specify it in `account_key`.
