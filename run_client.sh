###write###
python3 run_rdma_test.py --role client --device rocep160s0 --server-ip 10.200.10.13 --size 4096 --qdepth 1024 --multi-port-server --threads 8 --log-csv --log-json --test-type write --base-port 18550 --client-id 0
###read###
#python3 run_rdma_test.py --role client --device rocep160s0 --server-ip 10.200.10.13 --size 4096 --qdepth 1024 --multi-port-server --threads 8 --log-csv --log-json --test-type read --base-port 18560 --client-id 0
###send###
#python3 run_rdma_test.py --role client --device rocep160s0 --server-ip 10.200.10.13 --size 4096 --qdepth 1024 --multi-port-server --threads 8 --log-csv --log-json --test-type send --base-port 18570 --client-id 0