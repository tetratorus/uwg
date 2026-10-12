# GPL-3 runtime for uwg.urban_heat. Build from the repository root:
#   docker build -f rewire/uwg.urban_heat/Dockerfile -t tetratorus/uwg-urban-heat:0.1.0 .
# Python is pinned to 3.11 (upstream CI matrix); see rewire/README.md "Python version" for why.
ARG BASE=mirror.gcr.io/library/python:3.11-slim
FROM ${BASE}
WORKDIR /opt/uwg
# uwg itself has no runtime dependencies (setup.py install_requires=[]); it is used from source via PYTHONPATH
# so the unmodified package code in ./uwg is exactly what runs (no setuptools_scm/.git needed in the image).
RUN pip install --no-cache-dir "pandas==2.2.3" "pyarrow==18.1.0" "numpy==2.2.6"
COPY LICENSE ./LICENSE
COPY uwg ./uwg
COPY resources/initialize_singapore.uwg resources/SGP_Singapore.486980_IWEC.epw ./resources/
COPY tests/matlab_ref/matlab_output/SGP_Singapore.486980_IWEC_UWG_Matlab.epw ./tests/matlab_ref/matlab_output/
COPY rewire/uwg.urban_heat/adapter.py rewire/uwg.urban_heat/runtime/run_uwg.py /opt/rewire/
COPY rewire/tools/freeze_goldens.py /opt/rewire/tools/
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/opt/uwg
CMD ["python", "/opt/rewire/run_uwg.py", "/spine/inputs", "/spine/params.json", "/spine/outputs"]
