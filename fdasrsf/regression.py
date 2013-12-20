"""
Warping Invariant Regression using SRSF

moduleauthor:: Derek Tucker <dtucker@stat.fsu.edu>

"""

import numpy as np
import fdasrsf.utility_functions as uf
from scipy import dot
from scipy.optimize import fmin_l_bfgs_b
from scipy.integrate import trapz
from scipy.linalg import inv, norm
from patsy import bs
from joblib import Parallel, delayed
import collections


def elastic_regression(f, y, time, B=None, lam=0, df=20, max_itr=20, cores=-1):
    """
    This function identifies a regression model with phase-variablity
    using elastic methods

    :param f: numpy ndarray of shape (M,N) of M functions with N samples
    :param y: numpy array of N responses
    :param time: vector of size N describing the sample points
    :param B: optional matrix describing Basis elements
    :param lam: regularization parameter (default 0)
    :param df: number of degrees of freedom B-spline (default 20)
    :param max_itr: maximum number of iterations (default 20)
    :param cores: number of cores for parallel processing (default all)
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

    # Create B-Spline Basis if none provided
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

        # OLS using basis
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
            out = Parallel(n_jobs=cores)(delayed(regression_warp)(beta,
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
                                   'qn', 'gamma', 'q', 'B', 'b',
                                   'SSE', 'type'])
    out = model(alpha, beta, fn, qn, gamma, q, B, b[1:-1], SSE[0:itr],
                'linear')
    return out


def elastic_logistic(f, y, time, B=None, df=20, max_itr=20, cores=-1):
    """
    This function identifies a logistic regression model with
    phase-variablity using elastic methods

    :param f: numpy ndarray of shape (M,N) of M functions with N samples
    :param y: numpy array of labels (1/-1)
    :param time: vector of size N describing the sample points
    :param B: optional matrix describing Basis elements
    :param df: number of degrees of freedom B-spline (default 20)
    :param max_itr: maximum number of iterations (default 20)
    :param cores: number of cores for parallel processing (default all)
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
    :return Loss: logistic loss

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

    # Create B-Spline Basis if none provided
    if B is None:
        B = bs(time, df=df, degree=4, include_intercept=True)
    Nb = B.shape[1]

    q = uf.f_to_srsf(f, time)

    gamma = np.tile(np.linspace(0, 1, M), (N, 1))
    gamma = gamma.transpose()

    itr = 1
    LL = np.zeros(max_itr)
    while itr <= max_itr:
        print("Iteration: %d" % itr)
        # align data
        fn = np.zeros((M, N))
        qn = np.zeros((M, N))
        for ii in range(0, N):
            fn[:, ii] = np.interp((time[-1] - time[0]) * gamma[:, ii] +
                                  time[0], time, f[:, ii])
            qn[:, ii] = uf.warp_q_gamma(time, q[:, ii], gamma[:, ii])

        Phi = np.ones((N, Nb+1))
        for ii in range(0, N):
            for jj in range(1, Nb+1):
                Phi[ii, jj] = trapz(qn[:, ii] * B[:, jj-1], time)

        # Find alpha and beta using l_bfgs
        b0 = np.zeros(Nb+1)
        out = fmin_l_bfgs_b(logit_loss, b0, fprime=logit_gradient,
                            args=(Phi, y), pgtol=1e-10, maxiter=200,
                            maxfun=250, factr=1e-30)
        b = out[0]
        alpha = b[0]
        beta = B.dot(b[1:Nb+1])
        beta = beta.reshape(M)

        # compute the logistic loss
        LL[itr - 1] = logit_loss(b, Phi, y)

        # find gamma
        gamma_new = np.zeros((M, N))
        if parallel:
            out = Parallel(n_jobs=cores)(delayed(logistic_warp)(beta, time,
                                         q[:, n], y[n]) for n in range(N))
            gamma_new = np.array(out)
            gamma_new = gamma_new.transpose()
        else:
            for ii in range(0, N):
                gamma_new[:, ii] = logistic_warp(beta, time, q[:, ii], y[ii])

        if norm(gamma - gamma_new) < 1e-5:
            break
        else:
            gamma = gamma_new

        itr += 1

    # Last Step with centering of gam
    gamma = gamma_new
    # gamI = uf.SqrtMeanInverse(gamma)
    # gamI_dev = np.gradient(gamI, 1 / float(M - 1))
    # beta = np.interp((time[-1] - time[0]) * gamI + time[0], time,
    #                  beta) * np.sqrt(gamI_dev)

    # for ii in range(0, N):
    #     qn[:, ii] = np.interp((time[-1] - time[0]) * gamI + time[0],
    #                           time, qn[:, ii]) * np.sqrt(gamI_dev)
    #     fn[:, ii] = np.interp((time[-1] - time[0]) * gamI + time[0],
    #                           time, fn[:, ii])
    #     gamma[:, ii] = np.interp((time[-1] - time[0]) * gamI + time[0],
    #                              time, gamma[:, ii])

    model = collections.namedtuple('model', ['alpha', 'beta', 'fn',
                                   'qn', 'gamma', 'q', 'B', 'b',
                                   'Loss', 'type'])
    out = model(alpha, beta, fn, qn, gamma, q, B, b[1:-1], LL[0:itr],
                'logistic')
    return out


def elastic_mlogistic(f, y, time, B=None, df=20, max_itr=20, cores=-1):
    """
    This function identifies a multinomial logistic regression model with
    phase-variablity using elastic methods

    :param f: numpy ndarray of shape (M,N) of M functions with N samples
    :param y: numpy array of labels {1,2,...,m} for m classes
    :param time: vector of size N describing the sample points
    :param B: optional matrix describing Basis elements
    :param df: number of degrees of freedom B-spline (default 20)
    :param max_itr: maximum number of iterations (default 20)
    :param cores: number of cores for parallel processing (default all)
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
    :return Loss: logistic loss

    """
    M = f.shape[0]
    N = f.shape[1]
    # Code labels
    m = y.max()
    Y = np.zeros((m, N), dtype=int)
    for ii in range(0, N):
        Y[y[ii]-1, ii] = 1

    if M > 500:
        parallel = True
    elif N > 100:
        parallel = True
    else:
        parallel = False

    binsize = np.diff(time)
    binsize = binsize.mean()

    # Create B-Spline Basis if none provided
    if B is None:
        B = bs(time, df=df, degree=4, include_intercept=True)
    Nb = B.shape[1]

    q = uf.f_to_srsf(f, time)

    gamma = np.tile(np.linspace(0, 1, M), (N, 1))
    gamma = gamma.transpose()

    itr = 1
    LL = np.zeros(max_itr)
    while itr <= max_itr:
        print("Iteration: %d" % itr)
        # align data
        fn = np.zeros((M, N))
        qn = np.zeros((M, N))
        for ii in range(0, N):
            fn[:, ii] = np.interp((time[-1] - time[0]) * gamma[:, ii] +
                                  time[0], time, f[:, ii])
            qn[:, ii] = uf.warp_q_gamma(time, q[:, ii], gamma[:, ii])

        Phi = np.ones((N, Nb+1))
        for ii in range(0, N):
            for jj in range(1, Nb+1):
                Phi[ii, jj] = trapz(qn[:, ii] * B[:, jj-1], time)

        # Find alpha and beta using l_bfgs
        b0 = np.zeros(
                      Nb+1)
        out = fmin_l_bfgs_b(mlogit_loss, b0, fprime=logit_gradient,
                            args=(Phi, Y), pgtol=1e-10, maxiter=200,
                            maxfun=250, factr=1e-30)
        b = out[0]
        alpha = b[0]
        beta = B.dot(b[1:Nb+1])
        beta = beta.reshape(M)

        # compute the logistic loss
        LL[itr - 1] = logit_loss(b, Phi, y)

        # find gamma
        gamma_new = np.zeros((M, N))
        if parallel:
            out = Parallel(n_jobs=cores)(delayed(logistic_warp)(beta, time,
                                         q[:, n], y[n]) for n in range(N))
            gamma_new = np.array(out)
            gamma_new = gamma_new.transpose()
        else:
            for ii in range(0, N):
                gamma_new[:, ii] = logistic_warp(beta, time, q[:, ii], y[ii])

        if norm(gamma - gamma_new) < 1e-5:
            break
        else:
            gamma = gamma_new

        itr += 1

    # Last Step with centering of gam
    gamma = gamma_new
    # gamI = uf.SqrtMeanInverse(gamma)
    # gamI_dev = np.gradient(gamI, 1 / float(M - 1))
    # beta = np.interp((time[-1] - time[0]) * gamI + time[0], time,
    #                  beta) * np.sqrt(gamI_dev)

    # for ii in range(0, N):
    #     qn[:, ii] = np.interp((time[-1] - time[0]) * gamI + time[0],
    #                           time, qn[:, ii]) * np.sqrt(gamI_dev)
    #     fn[:, ii] = np.interp((time[-1] - time[0]) * gamI + time[0],
    #                           time, fn[:, ii])
    #     gamma[:, ii] = np.interp((time[-1] - time[0]) * gamI + time[0],
    #                              time, gamma[:, ii])

    model = collections.namedtuple('model', ['alpha', 'beta', 'fn',
                                   'qn', 'gamma', 'q', 'B', 'b',
                                   'Loss', 'type'])
    out = model(alpha, beta, fn, qn, gamma, q, B, b[1:-1], LL[0:itr],
                'mlogistic')
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
        q_tmp = uf.warp_q_gamma(time, q[:, ii],
                                model.gamma[:, dist.argmin()])
        if model.type == 'linear':
            y_pred[ii] = model.alpha + trapz(q_tmp * model.beta, time)
        elif model.type == 'logistic':
            y_pred[ii] = model.alpha + trapz(q_tmp * model.beta, time)

    if y is None:
        if model.type == 'linear':
            SSE = None
        elif model.type == 'logistic':
            y_pred = phi(y_pred)
            y_labels = np.ones(n)
            y_labels[y_pred < 0.5] = -1
            PC = None
    else:
        if model.type == 'linear':
            SSE = sum((y - y_pred) ** 2)
        elif model.type == 'logistic':
            y_pred = phi(y_pred)
            y_labels = np.ones(n)
            y_labels[y_pred < 0.5] = -1
            TP = sum(y[y_labels == 1] == 1)
            FP = sum(y[y_labels == -1] == 1)
            TN = sum(y[y_labels == -1] == -1)
            FN = sum(y[y_labels == 1] == -1)
            PC = (TP+TN)/(TP+FP+FN+TN)

    if model.type == 'linear':
        prediction = collections.namedtuple('prediction', ['y_pred', 'SSE'])
        out = prediction(y_pred, SSE)
    elif model.type == 'logistic':
        prediction = collections.namedtuple('prediction', ['y_prob',
                                            'y_labels', 'PC'])
        out = prediction(y_pred, y_labels, PC)

    return out


# helper functions for linear regression
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


# helper functions for logistic regression
def logistic_warp(beta, time, q, y):
    if y == 1:
        gamma = uf.optimum_reparam(beta, time, q)
    elif y == -1:
        gamma = uf.optimum_reparam(-1*beta, time, q)
    return gamma


def phi(t):
    # logistic function, returns 1 / (1 + exp(-t))
    idx = t > 0
    out = np.empty(t.size, dtype=np.float)
    out[idx] = 1. / (1 + np.exp(-t[idx]))
    exp_t = np.exp(t[~idx])
    out[~idx] = exp_t / (1. + exp_t)
    return out


def logit_loss(b, X, y):
    # logistic loss function, returns Sum{-log(phi(t))}
    z = X.dot(b)
    yz = y * z
    idx = yz > 0
    out = np.zeros_like(yz)
    out[idx] = np.log(1 + np.exp(-yz[idx]))
    out[~idx] = (-yz[~idx] + np.log(1 + np.exp(yz[~idx])))
    out = out.sum()
    return out


def logit_gradient(b, X, y):
    # gradient of the logistic loss
    z = X.dot(b)
    z = phi(y * z)
    z0 = (z - 1) * y
    grad = X.T.dot(z0)
    return grad


def logit_hessian(s, b, X, y):
    # hessian of the logistic loss
    z = X.dot(b)
    z = phi(y * z)
    d = z * (1 - z)
    wa = d * X.dot(s)
    Hs = X.T.dot(wa)
    out = Hs
    return out


# helper functions for multinomial logistic regression
def mlogit_loss(B, X, Y):
    # multinomial logistic loss (negative log-likelihood)
    m = Y.shape[0]
    N = Y.shape[1]
    out = np.zeros(N)
    for i in range(0, N):
        tmp = np.zeros(m)
        tmp1 = np.zeros(m)
        for j in range(0, m):
            tmp[j] = Y[j, i] * B[j, :].dot(X[i, :].T)
            tmp1[j] = np.exp(B[j, :].dot(X[i, :].T))

        out[i] = tmp.sum() - np.log(tmp1.sum())

    out = -1*out.sum()
    return out


def mlogit_gradient(B, X, Y):
    # gradient of the multinomial logistic loss
    m = Y.shape[0]
    N = Y.shape[1]
    M = X.shape[1]
    grad = np.zeros((m, M))
    for k in range(0, m):
        tmp = np.zeros((M, N))
        for i in range(0, N):
            tmp1 = Y[k, i] * X[i, :].T
            tmp2 = np.zeros(m)
            for j in range(0, m):
                tmp2[j] = np.exp(B[j, :].dot(X[i, :].T))

            tmp[:, i] = tmp1 - 1/tmp2.sum() * np.exp(B[k, :].dot(X[i, :].T)) * X[i, :]

        grad[k, :] = -1*tmp.sum(axis=1)

    return grad
