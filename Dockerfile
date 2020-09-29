FROM jupyter/scipy-notebook

MAINTAINER Pierre Navaro <pierre.navaro@univ-rennes1.fr>

USER root

COPY . ${HOME}

RUN chown -R ${NB_USER} ${HOME}

USER $NB_USER

RUN pip install --user findblas && python setup.py install --user
