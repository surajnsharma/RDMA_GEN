## Server options available
###write###
python3 run_rdma_test.py --role server --device rocep160s0 --size 65536 --qdepth 1024 --threads 8 --log-csv --log-json --test-type write --base-port 18550 --multi-port-server --enable-prometheus
###read###
#python3 run_rdma_test.py --role server --device rocep160s0 --size 4096 --qdepth 1024 --multi-port-server --threads 8 --log-csv --log-json --test-type read --base-port 18560
###send###
#python3 run_rdma_test.py --role server --device rocep160s0 --size 4096 --qdepth 1024 --multi-port-server --threads 8 --log-csv --log-json --test-type send --base-port 18570
