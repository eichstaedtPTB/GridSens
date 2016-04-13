# -*- coding: utf-8 -*-
"""
This module contains different state estimation approaches related to the Kalman filter.


@author: Sascha Eichstaedt
original MATLAB code by Wiebke Heins (TU Clausthal)

"""

import numpy as np
from scipy.sparse import issparse

if __name__=="NLO.nodal_load_observer": # module is imported from within package
	from tools.data_tools import process_admittance, separate_Yslack, makeYbus
else:
	from ..tools.data_tools import process_admittance, separate_Yslack, makeYbus


def get_system_matrices(pmeas,qmeas,vmeas):
	"""Construction of matrices Cm, Dm and Dnm which map all power/voltage values to the actual
	measured/non-measured ones.

	:param pmeas: (n_K,) shaped array of booleans indicating measurement positions of active power
	:param qmeas: (n_K,) shaped array of booleans indicating measurement positions of reactive power
	:param vmeas: (n_K,) shaped array of booleans indicating measurement positions of voltage
	"""
	assert(len(pmeas)==len(qmeas))
	# assert(len(qmeas)==len(vmeas))

	n_K = len(pmeas)

# construction of matrix Cm
	m = vmeas.nonzero()[0]
	r = len(m)
	Cm = np.zeros((2*r,2*n_K))
	for i in range(r):
		Cm[i,m[i]] = 1
		Cm[r+i,n_K+m[i]] = 1

# construction of matrix Dm
	pm = len(pmeas.nonzero()[0])
	qm = len(qmeas.nonzero()[0])
	Dm = np.zeros((2*n_K, pm+qm),dtype=int)  # (Eq.4.78) in WH thesis
	for k,ind in enumerate(pmeas.nonzero()[0]):
		Dm[ind,k] = 1
	for k,ind in enumerate(qmeas.nonzero()[0]):
		Dm[n_K+ind,pm+k] = 1

# construction of matrix Dnm
	pnmeas = -pmeas[:]
	qnmeas = -qmeas[:]
	pnm = len(pnmeas.nonzero()[0])
	qnm = len(qnmeas.nonzero()[0])
	Dnm = np.zeros((2*n_K, pnm+qnm))  # (Eq.4.78) in WH thesis
	for k,ind in enumerate(pnmeas.nonzero()[0]):
		Dnm[ind,k] = 1
	for k,ind in enumerate(qnmeas.nonzero()[0]):
		Dnm[n_K+ind,pnm+k] = 1

	return Cm, Dnm, Dm




def jacobian(Y00,Ys,V,Vs):
	"""
	Calculation of jacobian matrix for the extended Kalman filter
	"""
	n_K = Y00.shape[0]/2
	G = Y00[:n_K,:n_K]
	B = Y00[n_K:,:n_K]
	Gs= Ys[:n_K,0]
	Bs= Ys[n_K:,0]

	n = V.shape[0]/2

	VsRe = Vs[0]
	VsIm = Vs[1]

	VRe = V[:n]
	VIm = V[n:]

	# Dh = [[H,N],[M,L]]
	H = np.zeros((n,n))
	N = np.zeros((n,n))

	# outer diagonal elements of H
	for i in range(n):
		for j in range(n):
			H[i,j] = 3*VRe[i]*G[i,j] + 3*VIm[i]*B[i,j]
	# diagonal elements
	for i in range(n):
		H[i,i] = 3*np.dot(G[i,:],VRe)- 3*np.dot(B[i,:],VIm) + 3*G[i,i]*VRe[i] + 3*B[i,i]*VIm[i] + 3*Gs[i]*VsRe - 3*Bs[i]*VsIm

	# outer diagonal elements of N
	for i in range(n):
		for j in range(n):
			N[i,j] = -3*VRe[i]*B[i,j] + 3*VIm[i]*G[i,j]
	# diagonal elements
	for i in range(n):
		N[i,i] = 3*np.dot(B[i,:],VRe) + 3*np.dot(G[i,:],VIm) - 3*B[i,i]*VRe[i] + 3*G[i,i]*VIm[i] + 3*Bs[i]*VsRe + 3*Gs[i]*VsIm

	# outer diagonal elements of M
	M = N.copy()
	# diagonal elements of M
	for i in range(n):
		M[i,i] = -3*np.dot(B[i,:],VRe) - 3*np.dot(G[i,:],VIm) -3*B[i,i]*VRe[i] + 3*G[i,i]*VIm[i] - 3*Bs[i]*VsRe - 3*Gs[i]*VsIm

	# outer diagonal elements of L
	L = -H.copy()
	# diagonal elements of L
	for i in range(n):
		L[i,i] = 3*np.dot(G[i,:],VRe) -3*np.dot(B[i,:],VIm) - 3*B[i,i]*VIm[i] - 3*G[i,i]*VRe[i] + 3*Gs[i]*VsRe - 3*Bs[i]*VsIm

	Dh = np.vstack((np.hstack((H,N)),
					np.hstack((M,L))))
	return Dh


def jacobian_dSdV(Y, nK):
	# Set up equations of power flow (bus power from nodal voltage) as symbolic equations and
	# calculate the corresponding Jacobian matrix.
	from sympy import symbols, Matrix

	G = Matrix(np.real(Y))
	B = Matrix(np.imag(Y))

	e_J = symbols("e1:%d"%(nK+1))
	f_J = symbols("f1:%d"%(nK+1))

	hSK = []
	for i in range(nK):
		hSK.append(e_J[i]*(G[i,:].dot(e_J) - B[i,:].dot(f_J)) + f_J[i]*(G[i,:].dot(f_J) + B[i,:].dot(e_J)))
	for i in range(nK):
		hSK.append(f_J[i]*(G[i,:].dot(e_J) - B[i,:].dot(f_J)) - e_J[i]*(G[i,:].dot(f_J) + B[i,:].dot(e_J)))
	hSK = Matrix(hSK)
	ef_J = e_J[1:] + f_J[1:]

	Jac_equ = hSK.jacobian(ef_J)

	return Jac_equ, hSK


def jacobian_dHdV(nK, y, cap, inds):
	# Set up equations of power flow (power at line from nodal voltage) as symbolic equations and
	# calculate the corresponding Jacobian matrix.
	from sympy import symbols, Matrix

	g = Matrix(np.real(y))
	b = Matrix(np.imag(y))

	e_J = symbols("e1:%d"%(nK+1))
	f_J = symbols("f1:%d"%(nK+1))
	hSluV = []

	if "Pl" in inds:
		nPl = np.asarray(inds["Pl"]).astype(int)
		for k in range(nPl.shape[0]):
			i,j = nPl[k,:]
			hSluV.append((e_J[i]**2+f_J[i]**2)*g[i,j]-(e_J[i]*e_J[j]+f_J[i]*f_J[j])*g[i,j]+(e_J[i]*f_J[j]-e_J[j]*f_J[i])*b[i,j])
	if "Ql" in inds:
		nQl = np.asarray(inds["Ql"]).astype(int)
		for k in range(nQl.shape[0]):
			i,j = nQl[k,:]
			hSluV.append(-(e_J[i]**2+f_J[i]**2)*b[i,j]+(e_J[i]*e_J[j]+f_J[i]*f_J[j])*b[i,j]+(e_J[i]*f_J[j]-e_J[j]*f_J[i])*g[i,j]-(e_J[i]**2+f_J[i]**2)*cap[i,j]/2)
	# if "Vm" in inds:
	# 	nVk = np.asarray(inds["Vm"]).astype(int)
	# 	for k in range(nVk.shape[0]):
	# 		i = nVk[k]
	# 		hSluV.append((e_J[i]**2+f_J[i]**2)**0.5)
	if len(hSluV)>0:
		hSluV = Matrix(hSluV)
		ef_J = e_J[1:] + f_J[1:]
		JMatrix_dHdV = hSluV.jacobian(ef_J)
		return JMatrix_dHdV, hSluV
	else:
		return None, None



def LinearKalmanFilter(topology, meas, meas_unc, meas_idx, pseudo_meas, model, V0,
						   Vs, slack_idx=0, Y=None): #topology, meas, meas_unc, meas_idx, pseudo_meas, model, v0=11.55, slack_idx=0, Y=None, nK=None):
	"""
	Quasi-Linear Kalman filter for the nodal load observer
	This version of the NLO state estimation method ignores the nonlinearity for the calculation of the
	Kalman gain and utilizes the fix point equation property for the calculation of voltages from powers.

	Real-valued matrices of complex-valued quantities are assumed to be structured as [ [real part], [imag part] ]
	:param topology: dict containing information on bus, branch, ... in PyPower format
	:param meas: dict containing measurements "Pk", "Qk", "Vm" and "Va"
	:param meas_unc: dict containing associated uncertainties
	:param meas_idx: dict containing the corresponding indices
	:param pseudo_meas: dict containing the corresponding pseudo-measurements
	:param model: DynamicModel object as defined in dynamic_models.py
	:param V0: initial estimate of nodal voltages (magnitude and phase)
	:param slack_idx: index of slack node
	:param Y: (optional) user defined admittance matrix

	"""
	if issparse(Y):
		Y = Y.toarray()

	if not isinstance(Y,np.ndarray):
		Y = makeYbus(topology["baseMVA"],topology["bus"],topology["branch"])
	Yadm, Y_slack = separate_Yslack(Y,slack_idx)

	nK = len(V0)/2
	pmeas = np.zeros(nK,dtype = bool); pmeas[meas_idx["Pk"]] = True
	qmeas = np.zeros(nK,dtype = bool); qmeas[meas_idx["Qk"]] = True
	vmeas = np.zeros(nK,dtype = bool); vmeas[meas_idx["Vm"]] = True
	Cm,Dnm,Dm = get_system_matrices(pmeas,qmeas,vmeas)

	Slack = np.linalg.solve(Yadm,np.dot(Y_slack,Vs))
	y = np.r_[meas["Vm"], meas["Va"]] + np.dot(Cm,Slack)

	S = np.dot(Dm, np.r_[meas["Pk"], meas["Qk"]]) + np.dot(Dnm, np.r_[pseudo_meas["Pk"], pseudo_meas["Qk"]])

	if isinstance(meas_unc["Vm"],float):
		meas_unc["Vm"] = meas_unc["Vm"]*np.ones_like(meas["Vm"])
	if isinstance(meas_unc["Va"],float):
		meas_unc["Va"] = meas_unc["Va"]*np.ones_like(meas["Va"])

	r = np.r_[meas_unc["Vm"]**2,
			  meas_unc["Va"]**2]
	R = np.diag(r)

	nx = model.dim
	nm = y.shape[0]
	t_f= y.shape[1]

	def calcM(mu):
		divisor = 3*(mu[:nK]**2 + mu[nK:]**2)
		return np.r_[np.c_[np.diag(mu[:nK]/divisor), np.diag(mu[nK:]/divisor)],
				     np.c_[np.diag(mu[nK:]/divisor), -np.diag(mu[:nK]/divisor)]]

	def calcKs(V,Sh,k,accuracy=1e-12):
		# According to W. Heins' Thesis calculation of V using Ks is a fix point equation
		# We take that into account by doing a fixed number of iterations of the corresponding
		# fix point iterations
		Vn = V.copy()
		fp_diff = 1.0
		maxiter = 20
		count = 0
		while fp_diff>accuracy and count < maxiter:
			tmp = Vn
			MU = calcM(Vn)
			Ks = np.linalg.solve(Yadm,MU)
			Vn = np.dot(Ks, np.dot(Dnm,Sh) + S[:,k]) - Slack[:,k]
			fp_diff = np.linalg.norm(tmp-Vn)
			count += 1
		return Ks


	P = model.forecast_unc()

# initialize solution matrices
	V_est = np.zeros((2*nK,t_f+1))     # Estimated voltages
	V_est[:nK,0] = V0[:nK]
	x_est = np.zeros((nx,t_f+1))          # Estimated active and reactive powers
	x_est[:,0] = model.forecast_state()
	DeltaS_est = np.zeros((nx,t_f))     # Estimated power deviation
	UncDeltaS = np.zeros_like(DeltaS_est)
	Dnm = model.adjust_Dnm(Dnm)

#%% ########################### KALMAN ########################################
	print '.',
	for k in range(1,t_f+1):
	# preparation of state space system matrices
		Ks = calcKs(V_est[:,k-1],x_est[:,k-1],k-1)
		C = np.dot(Cm,np.dot(Ks,Dnm))
		D = np.dot(Cm,Ks)
#========================== actual Kalman filter part =========================
	#  Kalman filter forecast step
		xf = model.forecast_state(x_est[:,k-1])[:,np.newaxis]
		Pf = model.forecast_unc(P)
	# Kalman gain matrix K
		K =  np.linalg.solve(np.dot(C,np.dot(Pf,C.T)) + R, np.dot(C,P)).T
	# corrected state estimate
		x_est[:,k][:,np.newaxis] = xf + np.dot(K, y[:,k-1].reshape(nm,1)
									  - (np.dot(C,xf) + np.dot(D,S[:,k-1].reshape(2*nK,1))) )
	# corrected error covariance matrix
		P = np.dot(np.eye(nx) - np.dot(K,C),Pf)
#==============================================================================
	# calculate voltage from estimated power
		V_est[:,k] = np.dot(Ks, np.dot(Dnm,x_est[:,k-1]) + S[:,k-1]) - Slack[:,k-1]
		DeltaS_est[:,k-1] = x_est[:,k]
		UncDeltaS[:,k-1] = np.sqrt(np.diag(P))
		print '.',
	print '.'
#%%

  # results
	S_est = S + np.dot(Dnm,DeltaS_est) # S_est = S + D_ng * DeltaS_est
	UncS  = np.zeros_like(S) + np.dot(Dnm,UncDeltaS)
	return S_est, V_est[:,1:], UncS, DeltaS_est,UncDeltaS



def IteratedExtendedKalman(topology, meas, meas_unc, meas_idx, pseudo_meas, model, V0,
						   Vs,slack_idx=0, Y=None, accuracy=1e-9, maxiter=5):
	"""
	Iterated Extended Kalman filter for the nodal load observer
	Real-valued matrices of complex-valued quantities are assumed to be structured as [ [real part], [imag part] ]

	:param topology: dict containing information on bus, branch, ... in PyPower format
	:param meas: dict containing measurements "Pk", "Qk", "Vm" and "Va"
	:param meas_unc: dict containing associated uncertainties
	:param meas_idx: dict containing the corresponding indices
	:param pseudo_meas: dict containing the corresponding pseudo-measurements
	:param model: DynamicModel object as defined in dynamic_models.py
	:param V0: initial estimate of nodal voltages at all nodes except slack
	:param Vs: voltage amplitude and phase at slack node
	:param slack_idx: index of slack node
	:param Y: (optional) admittance matrix
	:param accuracy: threshold for inner iteration of the iterated EKF
	:param maxiter: maximum number of inner iterations of the iterated EKF

	:return: Shat, Vhat, uShat, DeltaS, uDeltaS
	"""

	n = model.dim
	n_K = len(V0)/2
	pmeas = np.zeros(n_K,dtype = bool); pmeas[meas_idx["Pk"]] = True
	qmeas = np.zeros(n_K,dtype = bool); qmeas[meas_idx["Qk"]] = True
	vmeas = np.zeros(n_K,dtype = bool); vmeas[meas_idx["Vm"]] = True
	Cm,Dnm,Dm = get_system_matrices(pmeas,qmeas,vmeas)
	if not isinstance(Y,np.ndarray):
		Y = makeYbus(topology["baseMVA"],topology["bus"],topology["branch"])
	Y00, Ys = separate_Yslack(Y,slack_idx)
	y0 = np.zeros((np.size(vmeas[meas_idx["Vm"]]),meas["V"].shape[1]))
	y1 = np.zeros((np.size(vmeas[meas_idx["Vm"]]),meas["V"].shape[1]))
	for k,ind in enumerate(vmeas.nonzero()[0]):
		y0[k,:] =  meas["V"][ind,:]
		y1[k,:] =  meas["V"][ind+n_K,:]
	y = np.vstack((y0,y1))  

	Slack = np.linalg.solve(Y00,np.dot(Ys,Vs))
	Sm = np.r_[meas["Pk"], meas["Qk"]]
	Sfc = np.r_[pseudo_meas["Pk"], pseudo_meas["Qk"]]

	u = np.dot(Dm,Sm) + np.dot(Dnm,Sfc)
	if isinstance(meas_unc["Vm"],float):
		meas_unc["Vm"] = meas_unc["Vm"]*np.ones_like(meas["Vm"])
	if isinstance(meas_unc["Va"],float):
		meas_unc["Va"] = meas_unc["Va"]*np.ones_like(meas["Va"])
	r = np.r_[meas_unc["Vm"]**2,
			  meas_unc["Va"]**2]
	R = np.diag(r)

	def calcM(mu):
		divisor = 3*(mu[:n_K]**2 + mu[n_K:]**2)
		return np.r_[np.c_[np.diag(mu[:n_K]/divisor), np.diag(mu[n_K:]/divisor)],
				     np.c_[np.diag(mu[n_K:]/divisor), -np.diag(mu[:n_K]/divisor)]]
	nT = y.shape[1]
	xhat = np.zeros((n,nT))
	Vhat = np.zeros((2*n_K,nT))
	Shat = np.zeros((2*n_K,nT))
	DeltaS = np.zeros_like(xhat)
	uDeltaS= np.zeros_like(xhat)
	Pfilter = model.forecast_unc()

	Dnm = model.adjust_Dnm(Dnm)

	for k in range(nT):
		if k==0:
			xhatfc = model.forecast_state()
			Pfilterfc = model.forecast_unc()
			mu = V0
		else:
			xhatfc = model.forecast_state(xhat[:,k-1])
			Pfilterfc = model.forecast_unc(Pfilter)
			mu = Vhat[:,k-1]
		eta = xhatfc
		varstop1 = 1
		j1 = 1
		while (varstop1 > accuracy) and (j1 < maxiter):
			M_U = calcM(mu)
			muiter = np.linalg.solve(Y00,np.dot(M_U,u[:,k] + np.dot(Dnm,eta))) - Slack[:,k] #np.linalg.solve(Y00, np.dot(Ys, Vs[:,k]))
			varstop2 = 1
			j2 = 1
			while (varstop2 > accuracy) and (j2 < maxiter):
				M_U = calcM(mu)
				temp2 = muiter.copy()
				muiter = np.linalg.solve(Y00,np.dot(M_U,u[:,k] + np.dot(Dnm,eta))) - np.linalg.solve(Y00, np.dot(Ys, Vs[:,k]))
				varstop2 = np.linalg.norm(muiter-temp2)
				j2 += 1
			mu = muiter
			Dh = jacobian(Y00,Ys,mu,Vs[:,k])
			H = np.dot(Cm, np.linalg.solve(Dh, Dnm))
			K = np.dot(Pfilterfc, np.linalg.solve((np.dot(H,np.dot(Pfilterfc,H.T))+R).T,H).T)
			temp1 = eta.copy()
			eta = xhatfc + np.dot(K, y[:,k] - np.dot(Cm,mu) - np.dot(H, xhatfc-eta))
			varstop1 = np.linalg.norm(temp1-eta)
			j1 += 1
		# Data assimilation step
		Pfilter = np.dot( np.eye(n) - np.dot(K,H), Pfilterfc)
		xhat[:,k] = eta
		Shat[:,k] = u[:,k] + np.dot(Dnm,xhat[:,k])
		Vhat[:,k] = mu
		DeltaS[:,k-1] = xhat[:,k]
		uDeltaS[:,k-1] = np.sqrt(np.diag(Pfilter))

	uS  = np.dot(Dnm,uDeltaS)

	return Shat, Vhat, uS, DeltaS, uDeltaS


def IteratedExtendedKalman_extended(topology, meas, meas_unc, meas_idx, pseudo_meas, model, V0,
						   Vs,slack_idx=0, Y=None, accuracy=1e-9, maxiter=5):
	"""
	Iterated Extended Kalman filter for the nodal load observer (extended to all kind of measurements)
	Real-valued matrices of complex-valued quantities are assumed to be structured as [ [real part], [imag part] ]

	In this variant of the NLO, calculation of voltages in each time step is carried out by fitting to bus power.
	The Kalman correction step uses nodal voltages, bus power and line power.

	:param topology: dict containing information on bus, branch, ... in PyPower format
	:param meas: dict containing measurements "Pk", "Qk", "Vm" and "Va"
	:param meas_unc: dict containing associated uncertainties
	:param meas_idx: dict containing the corresponding indices
	:param pseudo_meas: dict containing the corresponding pseudo-measurements
	:param model: DynamicModel object as defined in dynamic_models.py
	:param V0: initial estimate of nodal voltages at all nodes except slack
	:param Vs: voltage amplitude and phase at slack node
	:param slack_idx: index of slack node
	:param Y: (optional) admittance matrix
	:param accuracy: threshold for inner iteration of the iterated EKF
	:param maxiter: maximum number of inner iterations of the iterated EKF

	:return: Shat, Vhat, uShat, DeltaS, uDeltaS
	"""
	meas_names =  ["Pk","Qk","Vm","Va","Pl","Ql"]
	meas, meas_idx, meas_unc = repair_meas(meas, meas_idx, meas_unc, expected_indices = meas_names)
	n = model.dim
	n_K = len(V0)/2

	if len(meas_idx["Pl"])>0 or len(meas_idx["Ql"])>0:
		has_line_measurements = True
	else:
		has_line_measurements = False

	non_ref = range(n_K+1) + range(n_K+1,2 * (n_K+1))
	non_ref.remove(slack_idx)
	non_ref.remove(n_K+slack_idx)

	pmeas = np.zeros(n_K,dtype = bool); pmeas[meas_idx["Pk"]] = True
	qmeas = np.zeros(n_K,dtype = bool); qmeas[meas_idx["Qk"]] = True
	vmeas = np.zeros(n_K,dtype = bool); vmeas[meas_idx["Vm"]] = True
	Cm,Dnm,Dm = get_system_matrices(pmeas,qmeas,vmeas)
	Dnm = model.adjust_Dnm(Dnm)

	if not isinstance(Y,np.ndarray):
		Y = makeYbus(topology["baseMVA"],topology["bus"],topology["branch"])
	Y00, Ys = separate_Yslack(Y, slack_idx)
	y, cap = calc_admittance(topology["branch"])[1:]
	J_dSdV, J_dHdV, f_hSK, f_hSl = network_equations(Y, y, cap, n_K+1, meas_idx)  # nK+1 due to slack bus

	full_V = lambda vv: np.r_[Vs[0, k], vv[:n_K], Vs[1, k], vv[n_K:]]

	Sm = np.r_[meas["Pk"], meas["Qk"]]
	Sfc = np.r_[pseudo_meas["Pk"], pseudo_meas["Qk"]]
	u = np.dot(Dm,Sm) + np.dot(Dnm,Sfc)
	nT = u.shape[1]

	if isinstance(meas_unc["Vm"],float):
		meas_unc["Vm"] = meas_unc["Vm"]*np.ones_like(meas["Vm"])
	if isinstance(meas_unc["Va"],float):
		meas_unc["Va"] = meas_unc["Va"]*np.ones_like(meas["Va"])

	xhat = np.zeros((n,nT))
	Vhat = np.zeros((2 * n_K, nT))
	Shat = np.zeros((2 * n_K, nT))
	DeltaS = np.zeros_like(xhat)
	uDeltaS= np.zeros_like(xhat)
	P = []

	def calcV(V, meas_k, umeas_k, k):
		"""Calculate nodal voltages by minimizing the difference between measured and calculated bus power using
		Newton's method
		:rtype: tuple
		:param meas_k: measured values
		:param umeas_k: uncertainties associated with measured values
		:return: V, h_V, Jacobian_V
		"""
		def voltage2buspower(v):
			EqPF = f_hSK(*full_V(v))[non_ref]
			JacSE = J_dSdV(*full_V(v))[non_ref]
			return EqPF, JacSE

		pf_stop = 1; pf_iter = 0
		Jac_SfromV = None
		SfromV = None
		S = np.dot(Dm,np.r_[meas_k['Pk'],meas_k['Qk']]) + np.dot(Dnm,Sfc[:,k])
		while pf_stop > accuracy and pf_iter < 10:
			SfromV, Jac_SfromV = voltage2buspower(V)
			delta_V = np.linalg.solve(Jac_SfromV, S - SfromV)
			V = V + delta_V
			pf_stop = np.linalg.norm(delta_V)
			pf_iter += 1
		return V, SfromV, Jac_SfromV

	for k in range(nT):
		meas_k, umeas_k = meas_at_time(meas,meas_unc,k,meas_names)
		if k == 0:
			xhatfc = model.forecast_state()
			Pfc = model.forecast_unc()
			mu  = V0
			if len(meas_idx['Vm'])>0:
				mu[meas_idx["Vm"]] = meas_k["Vm"][:]
			if len(meas_idx['Va'])>0:
				mu[n_K+np.asarray(meas_idx["Va"])] = meas_k["Va"][:]
			xhat[:,k] = xhatfc[:]
			P.append(Pfc)
			Shat[:, k] = u[:, k] + np.dot(Dnm, xhat[:, k])
			Vhat[:,k] = mu.copy()
			continue
		else:
			xhatfc = model.forecast_state(xhat[:, k - 1])
			Pfc = model.forecast_unc(P[k - 1])
			mu = Vhat[:, k - 1].copy()
			if len(meas_idx['Vm'])>0:
				mu[meas_idx["Vm"]] = meas_k["Vm"]
			if len(meas_idx['Va'])>0:
				mu[n_K+np.asarray(meas_idx["Va"])] = meas_k["Va"]

		Meas, R = construct_meas_vector(meas_k,umeas_k,meas_names)
		iekf_stop = 1; j1 = 1
		eta = xhatfc
		while (iekf_stop > accuracy) and (j1 < maxiter):
			V, SV, JdSdV = calcV(mu, meas_k, umeas_k, k)
			if has_line_measurements:
				JdhdV = np.r_[np.dot(Dm.T, JdSdV), J_dHdV(*full_V(V))]
				Eq1 = np.dot(Dm.T, V)
				Eq2 = f_hSl(*full_V(V))
				h = np.r_[Eq1, Eq2]
			else:
				JdhdV = np.dot(Dm.T, JdSdV)
				h = np.dot(Dm.T, V)

			JdVdDS = np.linalg.solve(J_dSdV(*full_V(V))[non_ref,:], Dnm)
			H = np.dot(JdhdV, JdVdDS)
			K = np.dot(Pfc, np.linalg.solve((np.dot(H, np.dot(Pfc, H.T)) + R).T, H).T)
			temp = eta.copy()
			eta = xhatfc + np.dot(K, Meas - h - np.dot(H, xhatfc - eta))
			iekf_stop = np.linalg.norm(temp-eta)
			j1 += 1
		P.append(np.dot(np.eye(n) - np.dot(K, H), Pfc))
		xhat[:, k] = eta
		Shat[:, k] = u[:, k] + np.dot(Dnm, xhat[:, k])
		Vhat[:, k] = V[:]
		DeltaS[:,k-1] = xhat[:,k]
		uDeltaS[:,k-1] = np.sqrt(np.diag(P[k]))
	uS = np.dot(Dnm, uDeltaS)

	return Shat, Vhat, uS, DeltaS, uDeltaS


def amph_phase_to_real_imag(A,P,UAP):
	"""
	Transforms uncertainties associated with amplitude and phase to the corresponding real and imaginary parts
	including the evaluation of associated standard uncertainties (ignoring correlations)

	For more details see
		Eichstädt, S. and Wilkens, V. "GUM2DFT – A software tool for uncertainty evaluation of transient signals in the frequency domain"
		Metrologia 2016

	:param A: ndarray of amplitude values; shape (N,)
	:param P: ndarray of phase values; shape (N,)
	:param UAP: ndarray of uncertainties associated with A and P; shape (2xN,)
	:return: Re, Im, URI
	"""
	from scipy import sparse

	assert(len(A.shape)==1)
	assert(A.shape==P.shape)
	assert(UAP.shape==(2*len(A),))
	# calculation of F
	Re = A*np.cos(P)
	Im = A*np.sin(P)

	# calculation of sensitivities
	CRA = np.cos(P)
	CRP = -A*np.sin(P)
	CIA = np.sin(P)
	CIP = A*np.cos(P)

	# assignment of uncertainty blocks in UAP
	N = len(A)
	Ua = UAP[:N]
	Up = UAP[N:]
	U11 = CRA*Ua*CRA + CRP*Up*CRP
	U12 = CRA*Ua*CIA + CRP*Up*CIP
	U22 = CIA*Ua*CIA + CIP*Up*CIP
	URI = sparse.diags([np.r_[U11,U22],U12,U12],[0,N,-N]).toarray()
	return Re, Im, URI


def meas_at_time(meas,meas_unc,ind,meas_names=None):
	"""Returns dictionary with the entries of meas at time index ind.
	:param meas: dict of measurements
	:param ind: time index
	:return: meas_ind
	"""
	meas_ind = dict([])
	umeas_ind = dict([])
	if not isinstance(meas_names,list):
		meas_names = meas.keys()
	for key in meas_names:
		if len(meas[key].shape)==2:
			meas_ind[key] = meas[key][:,ind]
		elif len(meas[key])>0:
			meas_ind[key] = meas[key][ind]
		else:
			meas_ind[key] = []

		if len(meas_unc[key].shape)==2:
			umeas_ind[key] = meas_unc[key][:,ind]
		elif len(meas_unc[key])>0:
			umeas_ind[key] = meas_unc[key][ind]
		else:
			umeas_ind[key] = []
	return meas_ind, umeas_ind


def construct_meas_vector(meas,meas_unc,meas_names=["Pk","Qk","Vm","Va"]):
	"""Returns numpy array of measurements and corresponding uncertainties/inverse weights
	:param meas: dict of measurement data at single time instant
	:param meas_unc: dict of measurement uncertainty at single time instant
	:param meas_idx: dict of measurement indices
	:return: Meas, R
	"""
	Meas = []
	for key in filter(lambda ind: len(meas[ind])>0, meas_names):
		Meas = np.r_[Meas,meas[key]]
	r = []
	for key in filter(lambda ind: len(meas[ind])>0, meas_names):
		if isinstance(meas_unc[key],float):
			r = np.r_[r, meas_unc[key]*np.ones_like(meas[key])]
		else:
			r = np.r_[r,meas_unc[key]]
	R = np.diag(r)

	return Meas, R


def network_equations(Y, y, cap, nK, meas_idx):
	"""Set up network equations to calculate estimates of bus power, power at line and voltages. This method uses
	 symbolic equations and calculates the Jacobian matrix with respect to nodal voltages.
	:param meas_idx: dict containg uncertainty associated with measurement data
	:return: J_dSdV, J_dHdV, f_hSK, f_hSl
	"""
	import sympy

	def makearray(Mat):
		M = np.array(Mat)
		if M.shape[1] == 1:
			return M.flatten()
		else:
			return M
	mat2array = [{'ImmutableMatrix': makearray}, 'numpy']

	JMatrix_dSdV, hSK = jacobian_dSdV(Y, nK)
	JMatrix_dHdV, hSluV = jacobian_dHdV(nK, y, cap, meas_idx)

	J_dSdV = sympy.lambdify(tuple(["e%d" % (i + 1) for i in range(nK)] + ["f%d" % (i + 1) for i in range(nK)]),
							JMatrix_dSdV, modules = mat2array)
	f_hSK = sympy.lambdify(tuple(["e%d" % (i + 1) for i in range(nK)] + ["f%d" % (i + 1) for i in range(nK)]), hSK,
						   modules = mat2array)
	if hSluV is None:
		J_dHdV = lambda *V: np.array([[]])
		f_hSl = lambda *V: np.array([])
	else:
		J_dHdV = sympy.lambdify(tuple(["e%d" % (i + 1) for i in range(nK)] + ["f%d" % (i + 1) for i in range(nK)]),
								JMatrix_dHdV, modules = mat2array)
		f_hSl = sympy.lambdify(tuple(["e%d" % (i + 1) for i in range(nK)] + ["f%d" % (i + 1) for i in range(nK)]), hSluV,
							  modules = mat2array)
	return J_dSdV, J_dHdV, f_hSK, f_hSl


def calc_admittance(network_branches):
	""" From network branch information in PyPower format calculate the bus and network admittances.

	:param network_branches: numpy array contain all information about the network branches
	:returns: bus admittance matrix Y, line admittances y and line capacitances cap

	"""
	nK = int(network_branches[:,:2].max())
	dim  = network_branches.shape[0]
	r = np.zeros((nK,nK))
	x = np.zeros_like(r)
	cap=np.zeros_like(r)        # Capacity between branch and earth

	for i in range(dim):
		k_start = network_branches[i,0]-1
		k_end = network_branches[i,1]-1
		r[k_start,k_end] = network_branches[i,2]
		x[k_start,k_end] = network_branches[i,3]
		cap[k_start,k_end]=network_branches[i,4]

	r += r.T
	x += x.T
	cap += cap.T
	z = r + 1j*x
	y = np.zeros_like(z)
	for i in range(nK):
		for j in range(nK):
			if z[i,j] != 0:
				y[i,j] = 1/z[i, j]
	Y = -y
	for i in range(nK):
		Y[i,i] = np.sum(y[i,:])+1j*np.sum(cap[i,:]/2)
	return Y, y, cap



def repair_meas(meas, meas_idx, meas_unc, expected_indices=None):
	"""
	The dictionaries meas, meas_idx and meas_unc are expected to contain certain keys.
	If any of these keys are missing, this function sets up corresponding default values.
	:param meas: dict containing measurement data
	:param meas_unc: dict containing uncertainty associated with measurement data
	:param meas_idx: dict containing index arrays indicating index of measurement in bus/branch array
	:return: meas, meas_idx, meas_unc
	"""
	if not isinstance(expected_indices,list):
		expected_indices = ['Pk','Qk','Vm','Va','Ql','Pl']

	for key in expected_indices:
		if key in meas:
			if not key in meas_idx: raise ValueError("Key %s in `meas`, but not in 'meas_idx'"%key)
			if not key in meas_unc:
				print "Uncertainty is not specified for measurements '%s'. Using sigma=20 %% instead."%key
				meas_unc[key] = np.ones_like(meas[key])*meas[key].max()*0.2
		else:
			meas[key] = np.array([])
			meas_idx[key] = []
			meas_unc[key] = np.array([])
	return meas, meas_idx, meas_unc