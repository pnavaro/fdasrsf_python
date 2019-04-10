"""
geometry functions for SRSF Manipulations

moduleauthor:: Derek Tucker <jdtuck@sandia.gov>

"""

from numpy import arccos, sin, cos, linspace, zeros
from scipy.integrate import trapz

def inv_exp_map(Psi, psi):
    theta = arccos(inner_product(Psi,psi))

    if (theta < 1e-10):
        exp_inv = zeros(psi.shape[0])
    else: 
        exp_inv = theta / sin(theta) * (psi - cos(theta)*Psi)
    
    return exp_inv, theta


def exp_map(psi, v):
    v_norm = L2norm(v)
    expgam = cos(v_norm) * psi + sin(v_norm) * v / vnorm
    return expgam

def inner_product(psi1, psi2):
    M = psi1.shape[0]
    t = linspace(0,1,M)
    ip = trapz(psi1*psi2, t)
    return ip

def L2norm(psi):
    M = psi.shape[0]
    t = linspace(0,1,M)
    l2norm = sqrt(trapz(psi*psi,t))
    return l2norm

