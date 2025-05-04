## NVIDIA NIC
python3 run_rdma_test.py --role client --device rocep160s0 --server-ip 10.200.10.13 --size 65536 --qdepth 1024 --threads 8 --log-csv --log-json --test-type write --base-port 18550 --client-id 0 --duration 10
