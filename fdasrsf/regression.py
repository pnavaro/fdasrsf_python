"""
Warping Invariant Regression using SRSF

moduleauthor:: Derek Tucker <dtucker@stat.fsu.edu>

"""

import numpy as np
import fdasrsf.utility_functions as uf
from scipy import dot
from scipy.integrate import trapz
from scipy.linalg import inv, norm
from patsy import bs
from joblib import Parallel, delayed
import collections


def elastic_regression(f, y, time, B=None, lam=0, df=20, max_itr=20):
    """
    This function identifies a regression model with phase-variablity
    using elastic methods

    :param f: numpy ndarray of shape (M,N) of M functions with N samples
    :param y: numpy array of N responses
    :param time: vector of size N describing the sample points
    :param B: optional matrix describing Basis elements
    :param lam: regularization parameter (default 0)
    :type f: np.ndarray
    :type time: np.ndarray

    :rtype: tuple of numpy array
    :return alpha: alpha parameter of model
    :return beta: beta(t) of model
    :return fn: aligned functions - numpy ndarray of shape (M,N) of M
    functions with N samples
    :return qn: aligned srvfs - similar structure to fn
    :return gamma: calculated warping functions
    :return q: original training SRSFs
    :return B: basis matrix
    :return b: basis coefficients
    :return SSE: sum of squared error

    """
    M = f.shape[0]
    N = f.shape[1]

    if M > 500:
        parallel = True
    elif N > 100:
        parallel = True
    else:
        parallel = False

    binsize = np.diff(time)
    binsize = binsize.mean()

    # Create B-Spline Basis if no provided
    if B is None:
        B = bs(time, df=df, degree=4, include_intercept=True)
    Nb = B.shape[1]

    # second derivative for regularization
    Bdiff = np.zeros((M, Nb))
    for ii in range(0, Nb):
        Bdiff[:, ii] = np.gradient(np.gradient(B[:, ii], binsize), binsize)

    q = uf.f_to_srsf(f, time)

    gamma = np.tile(np.linspace(0, 1, M), (N, 1))
    gamma = gamma.transpose()

    itr = 1
    SSE = np.zeros(max_itr)
    while itr <= max_itr:
        print("Iteration: %d" % itr)
        # align data
        fn = np.zeros((M, N))
        qn = np.zeros((M, N))
        for ii in range(0, N):
            fn[:, ii] = np.interp((time[-1] - time[0]) * gamma[:, ii] +
                                  time[0], time, f[:, ii])
            qn[:, ii] = uf.warp_q_gamma(time, q[:, ii], gamma[:, ii])

        # OLS using basis since we have it in this example
        Phi = np.ones((N, Nb+1))
        for ii in range(0, N):
            for jj in range(1, Nb+1):
                Phi[ii, jj] = trapz(qn[:, ii] * B[:, jj-1], time)

        R = np.zeros((Nb+1, Nb+1))
        for ii in range(1, Nb+1):
            for jj in range(1, Nb+1):
                R[ii, jj] = trapz(Bdiff[:, ii-1] * Bdiff[:, jj-1], time)

        xx = dot(Phi.T, Phi)
        inv_xx = inv(xx + lam * R)
        xy = dot(Phi.T, y)
        b = dot(inv_xx, xy)

        alpha = b[0]
        beta = B.dot(b[1:Nb+1])
        beta = beta.reshape(M)

        # compute the SSE
        int_X = np.zeros(N)
        for ii in range(0, N):
            int_X[ii] = trapz(qn[:, ii] * beta, time)

        SSE[itr - 1] = sum((y.reshape(N) - alpha - int_X) ** 2)

        # find gamma
        gamma_new = np.zeros((M, N))
        if parallel:
            out = Parallel(n_jobs=-1)(delayed(regression_warp)(beta,
                                      time, q[:, n], y[n], alpha) for n in range(N))
            gamma_new = np.array(out)
            gamma_new = gamma_new.transpose()
        else:
            for ii in range(0, N):
                gamma_new[:, ii] = regression_warp(beta, time, q[:, ii],
                                                   y[ii], alpha)

        if norm(gamma - gamma_new) < 1e-5:
            break
        else:
            gamma = gamma_new

        itr += 1

    # Last Step with centering of gam
    gamI = uf.SqrtMeanInverse(gamma_new)
    gamI_dev = np.gradient(gamI, 1 / float(M - 1))
    beta = np.interp((time[-1] - time[0]) * gamI + time[0], time,
                     beta) * np.sqrt(gamI_dev)

    for ii in range(0, N):
        qn[:, ii] = np.interp((time[-1] - time[0]) * gamI + time[0],
                              time, qn[:, ii]) * np.sqrt(gamI_dev)
        fn[:, ii] = np.interp((time[-1] - time[0]) * gamI + time[0],
                              time, fn[:, ii])
        gamma[:, ii] = np.interp((time[-1] - time[0]) * gamI + time[0],
                                 time, gamma_new[:, ii])

    model = collections.namedtuple('model', ['alpha', 'beta', 'fn',
                                   'qn', 'gamma', 'q', 'B', 'b', 'SSE'])
    out = model(alpha, beta, fn, qn, gamma, q, B, b[1:-1], SSE[0:itr])
    return out


def elastic_prediction(f, time, model, y=None):
    """
    This function identifies a regression model with phase-variablity
    using elastic methods

    :param f: numpy ndarray of shape (M,N) of M functions with N samples
    :param time: vector of size N describing the sample points
    :param model: indentified model from elastic_regression
    :param y: truth, optional used to calculate SSE

    :rtype: tuple of numpy array
    :return alpha: alpha parameter of model
    :return beta: beta(t) of model
    :return fn: aligned functions - numpy ndarray of shape (M,N) of M
    functions with N samples
    :return qn: aligned srvfs - similar structure to fn
    :return gamma: calculated warping functions
    :return q: original training SRSFs
    :return B: basis matrix
    :return b: basis coefficients
    :return SSE: sum of squared error

    """
    q = uf.f_to_srsf(f, time)
    n = q.shape[1]

    y_pred = np.zeros(n)
    for ii in range(0, n):
        diff = model.q - q[:, ii][:, np.newaxis]
        dist = np.sum(np.abs(diff) ** 2, axis=0) ** (1. / 2)
        q_tmp = uf.warp_q_gamma(time, q[:, ii], model.gamma[:, dist.argmin()])
        y_pred[ii] = model.alpha + trapz(q_tmp * model.beta, time)

    if y is None:
        SSE = None
    else:
        SSE = sum((y - y_pred) ** 2)

    prediction = collections.namedtuple('prediction', ['y_pred', 'SSE'])
    out = prediction(y_pred, SSE)
    return out


def regression_warp(beta, time, q, y, alpha):
    gam_M = uf.optimum_reparam(beta, time, q)
    qM = uf.warp_q_gamma(time, q, gam_M)
    y_M = trapz(qM * beta, time)

    gam_m = uf.optimum_reparam(-1 * beta, time, q)
    qm = uf.warp_q_gamma(time, q, gam_m)
    y_m = trapz(qm * beta, time)

    if y > alpha + y_M:
        gamma_new = gam_M
    elif y < alpha + y_m:
        gamma_new = gam_m
    else:
        gamma_new = uf.zero_crossing(y - alpha, q, beta, time, y_M, y_m,
                                     gam_M, gam_m)

    return gamma_new
