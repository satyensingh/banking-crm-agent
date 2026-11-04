FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
COPY chainlit_app.py chainlit.md ./
COPY .chainlit ./.chainlit
# One image, two services (see docker-compose.yml): the MCP tool server and the Chainlit chat UI.
EXPOSE 8000 8001
CMD ["python", "-m", "app.mcp_server"]
