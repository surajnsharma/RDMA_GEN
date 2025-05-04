## Server options available
python3 run_rdma_test.py --role server --device rocep160s0 --size 65536 --qdepth 1024 --threads 8 --log-csv --log-json \
--test-type write --base-port 18550 --latency lat