# Aircraft Maintenance Assistant — Streamlit (Render-ready)
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .
COPY pages/ pages/
COPY .streamlit/ .streamlit/
COPY src/ src/
COPY data/ data/

EXPOSE 10000
ENV PORT=10000
#CMD ["sh", "-c", "streamlit run app.py --server.address=0.0.0.0 --server.port=${PORT}"]
CMD uvicorn api:app --host 0.0.0.0 --port $PORT
