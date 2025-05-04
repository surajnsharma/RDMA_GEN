#AMD
run_rdma_test.py --role client --device rocep184s0 --server-ip 10.200.2.19 --size 4096 --qdepth 1 --threads 8 --log-csv --log-json --test-type write --base-port 18560 --client-id 0 --duration 10