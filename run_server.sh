###write###
python3 run_rdma_test.py --role server --device rocep160s0 --size 4096 --qdepth 1024 --multi-port-server --threads 8 --log-csv --log-json --test-type write --base-port 185550
###read###
#python3 run_rdma_test.py --role server --device rocep160s0 --size 4096 --qdepth 1024 --multi-port-server --threads 8 --log-csv --log-json --test-type read --base-port 185560
###send###
#python3 run_rdma_test.py --role server --device rocep160s0 --size 4096 --qdepth 1024 --multi-port-server --threads 8 --log-csv --log-json --test-type send --base-port 185570
