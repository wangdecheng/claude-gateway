当前容器状态：

high-api-postgres-1   postgres:16   Up   0.0.0.0:5432->5432/tcp

连接信息来自 docker-compose.yml：

Host: localhost
Port: 5432
User: high_api
Password: high_api_dev
Database: high_api

你可以用下面命令查看日志：

docker compose logs -f postgres

停止：

docker compose down