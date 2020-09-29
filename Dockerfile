FROM jupyter/scipy-notebook

MAINTAINER Pierre Navaro <pierre.navaro@univ-rennes1.fr>

USER root

COPY . ${HOME}

RUN chown -R ${NB_USER} ${HOME}

USER $NB_USER

RUN conda env update --quiet -f binder/environment.yml && \
    conda clean --all -f -y && \
    fix-permissions $CONDA_DIR && \
    fix-permissions /home/$NB_USER

RUN conda run python setup.py install --user
