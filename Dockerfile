FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements-streamlit.txt ./
RUN pip install --upgrade pip && pip install -r requirements-streamlit.txt

COPY streamlit_app.py ./
COPY worldquant_api_starter.py ./
COPY alpha_tuner.py ./
COPY alpha_samples_1000.txt ./

EXPOSE 8000

CMD ["sh", "-c", "streamlit run streamlit_app.py --server.address 0.0.0.0 --server.port ${PORT:-8000} --server.headless true"]
