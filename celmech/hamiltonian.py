from sympy import S, diff, lambdify, symbols, Matrix, Expr
from collections import MutableMapping
import pprint
from numpy import array
from collections import OrderedDict, UserDict
import numpy as np
from scipy.integrate import ode
import scipy.special
from .miscellaneous import poisson_bracket

def _my_elliptic_e(*args):
    if len(args) == 1:
        return scipy.special.ellipe(*args)
    else:
        return scipy.special.ellipeinc(*args)

_lambdify_kwargs = {'modules':['numpy', {
    'elliptic_k': scipy.special.ellipk,
    'elliptic_f': scipy.special.ellipkinc,
    'elliptic_e': _my_elliptic_e
    }]} 

# Should reduce hamiltonian only check for cyclic q, and then set both q and p as parameters? 
# There are cases where p shows up in hamiltonian but not q

# Do we call update in fullqp setter? Do we add a needs_update that only gets called on integrate(or others)?

# units in canonical transformation, Ham doesn't know about that

# All params and units are owned by Hamiltonians. PhaseSpaceStates are just numbers with no
# knowledge of units. 

# tracked and untracked variables handled by Hamiltonian
# we do want to be able to set things in phasespacestate from hamiltonian and update hamiltonian
# state is a property in hamiltonian that sets update if we call setter, and can handle the logic on 
# which phasepsacestate variables to return based on which dof are being tracked or not

# full values gives additional variables including conserved quantitties

class PhaseSpaceState(object):
    """
    A general class for describing the phase-space state
    of a Hamiltonian dynamical system.
    
    Attributes
    ----------
    qp : OrderedDict
        An ordered dictionary containing the canonical
        coordiantes and momenta as keys and their numerical
        values as dictionary values.
    qp_vars : list
        List of variable symbols used for the canonical
        coordinates and momenta.
    qp_pairs : list
        A list of the 2-tuples :math:`(q_i,p_i)`.
    N_dof : int
        The number of degrees of freedom.
    values : list
        List of the numerical values of `qp_vars`.
    """
    def __init__(self, qp_vars, values, t = 0):
        """
        Arguments
        ---------
        qp_vars : list of symbols
            List of symbols to use for the canonical coordiantes
            and momenta. The list should be of length 2*N for an
            integer N with entries 0,...,N-1 representing the
            canonical coordiante variables and entries N,...,2*N-1
            representing the corresponding conjugate momenta.
        values : array-like
            The numerical values assigned to the canonical coordiantes
            and momenta.
        t : float, optional
            The current time of system represented by the phase-space
            state. Default value is 0.
        """
        self.t = t
        msg="'qp_vars' and 'values' must have the same dimension."
        assert len(qp_vars)==len(values), msg
        self.qp = OrderedDict(zip(qp_vars, values))

    @property
    def qp_vars(self):
        return list(self.qp.keys()) 

    @property
    def qp_pairs(self):
        return [(self.qp_vars[i], self.qp_vars[i+self.N_dof]) for i in range(self.N_dof)]

    @property 
    def N_dim(self):
        return len(self.qp_vars)

    @property 
    def N_dof(self):
        return int(self.N_dim/2)

    @property
    def values(self):
        return list(self.qp.values()) 
    @values.setter
    def values(self,values):
        for key, value in zip(self.qp_vars, values):
            self.qp[key] = value

    def __str__(self):
        s = "t={0}".format(self.t)
        for var, val in self.qp.items():
            s += ", {0}={1}".format(var, val)
        return s
    def __repr__(self):
        return "PhaseSpaceState(qp_vars={0}, values={1}, t={2})".format(self.qp_vars, self.values, self.t)

class Fullqp(MutableMapping):
    def __init__(self, hamiltonian):
        self.hamiltonian = hamiltonian

    def __getitem__(self, key):
        try: # first try to find in the dynamical variables qp, if not, look for conserved quantities in H_params (in case of reduced hamiltonian)
            return self.hamiltonian.qp[key]
        except:
            try:
                return self.hamiltonian.H_params[key]
            except:
                raise AttributeError('Variable {0} not found'.format(key))

    def __setitem__(self, key, value):
        try: # first try to find in the dynamical variables qp, if not, look for conserved quantities in H_params (in case of reduced hamiltonian)
            self.hamiltonian.qp[key] = value
        except:
            try:
                self.hamiltonian.H_params[key] = value
                self.hamiltonian._needs_update = True
            except:
                raise AttributeError('Variable {0} not found'.format(key))

    def __delitem__(self, key):
        raise AttributeError("deleting variables not implemented.")

    def __iter__(self):
        for key in self.hamiltonian.full_qp_vars:
            yield key

    def __len__(self):
        return len(self.hamiltonian.full_qp_vars)

class ParamDict(UserDict):
    def __init__(self, hamiltonian, params):
        self.hamiltonian = hamiltonian
        super().__init__(params)

    def __setitem__(self, key, value):
        self.hamiltonian._needs_udpate = True
        super().__setitem__(key, value)

class Hamiltonian(object):
    """
    A general class for describing and evolving Hamiltonian systems.

    Attributes
    ----------

    state : object
        An object that stores the dynamical state of the system.

    H : sympy expression
        Symbolic expression for system's Hamiltonian.

    pqpars : list
        List of canonical variable pairs. 
    """
    def __init__(self, H, H_params, state, full_qp_vars=None):
        """
        Arguments
        ---------
        H : sympy expression
            Hamiltonian made up only of sympy symbols in state.qp_pairs and keys in H_params
        H_params : dict
            dictionary from sympy symbols for the constant parameters in H to their value
        state : PhaseSpaceState 
            Object for holding the dynamical state.
        
        In addition to the above, one needs to write 2 methods to map between the two objects:
        def state_to_list(self, state): 
            returns a list of values from state in the same order as pqpairs e.g. [P1,Q1,P2,Q2]
        def update_state_from_list(self, state, y, t):
            updates state object from a list of values y for the variables in the same order as pqpairs
            and integrator time 't'
        """
        self._H_params = ParamDict(self, H_params)
        self._H = H
        self.state = state
        self._full_qp_vars = full_qp_vars
        self._needs_update = True
        
    @property
    def t(self):
        return self.state.t

    @property
    def H(self):
        return self._H
    @H.setter
    def H(self, H):
        self._H = H
        self._needs_update = True
    
    @property
    def H_params(self):
        return self._H_params
    
    @property 
    def N_dim(self):
        return self.state.N_dim
    
    @property 
    def full_N_dim(self):
        return len(self.full_qp_vars)

    @property 
    def N_dof(self):
        return self.state.N_dof
    
    @property 
    def full_N_dof(self):
        return int(self.full_N_dim/2)

    @property
    def qp(self):
        return self.state.qp
    
    @property
    def full_qp(self):
        full_qp = Fullqp(self)
        return full_qp
    
    @property
    def qp_pairs(self):
        return self.state.qp_pairs
    
    @property
    def full_qp_pairs(self):
        if self._full_qp_vars:
            return [(self._full_qp_vars[i], self.full_qp_vars[i+self.full_N_dof]) for i in range(self.full_N_dof)]
        else:
            return self.qp_pairs

    @property
    def qp_vars(self):
        return self.state.qp_vars
    
    @property
    def full_qp_vars(self):
        if self._full_qp_vars:
            return self._full_qp_vars
        else:
            return self.qp_vars
    
    @property
    def values(self):
        return self.state.values
    
    @property
    def full_values(self):
        return list(self.full_qp.values())
    
    @property
    def N_H(self):
        if self._needs_update:
            self._update()
        return self._N_H
    
    @property
    def Energy(self):
        if self._needs_update:
            self._update()
        return self._Energy
    
    @property
    def derivs(self):
        if self._needs_update:
            self._update()
        return self._derivs

    @property
    def N_derivs(self):
        if self._needs_update:
            self._update()
        return self._N_derivs

    @property
    def flow(self):
        if self._needs_update:
            self._update()
        return self._flow
    
    @property
    def N_flow(self):
        if self._needs_update:
            self._update()
        return self._N_flow
    
    @property
    def jac(self):
        if self._needs_update:
            self._update()
        return self._jac

    @property
    def N_jac(self):
        if self._needs_update:
            self._update()
        return self._N_jac
    
    @property
    def integrator(self):
        if self._needs_update:
            self._update()
        return self._integrator
     
    def Lie_deriv(self,exprn):
        r"""
        Return the Lie derivative of an expression with respect to the Hamiltonian.
        In other word, compute 

        .. math::
            \mathcal{L}_{H}f

        where :math:`f` is the argument passed and :math:`\mathcal{L}_H \equiv [\cdot,H]` 
        is the Lie derivative operator.

        Arguments
        ---------
        exprn : sympy expression
            The expression to take the Lie derivative of.

        Returns
        -------
        sympy expression
            sympy expression for the resulting derivative.
        """
        return poisson_bracket(exprn,self.H,self.qp_vars,[])

    def N_Lie_deriv(self,exprn):
        r"""
        Return the Lie derivative of an expression with respect to the Hamiltonian
        with numerical values substituted for parameters. Equivalent to 
        :meth:`~poincare.Hamiltonian.N_Lie_deriv` but using the NH attribute 
        rather than the H attribute to compute brackets.  

        Arguments
        ---------
        exprn : sympy expression
            The expression to take the Lie derivative of.

        Returns
        -------
        sympy expression
            sympy expression for the resulting derivative.
        """
        return poisson_bracket(exprn,self._N_H,self.qp_vars,[])

    def integrate(self, time, integrator_kwargs={}):
        """
        Evolve Hamiltonian system from current state
        to input time by integrating the equations of 
        motion.

        Arguments
        ---------
        time : float
            Time to advance Hamiltonian system to.
        integrator_kwargs : dict,optional
            A dictionary of integrator keyword arguments
            to pass to the integrator. ``celmech`` uses
            the scipy.ode 'dop853' integrator.  Valid 
            keyword options can be found 
            `here <https://docs.scipy.org/doc/scipy/reference/generated/scipy.integrate.ode.html>`_.
        """
        # can we remove this block?
        try:
            self.integrator.integrate(time)
        except:
            raise AttributeError("Need to initialize Hamiltonian")
        self.state.t = self.integrator.t
        self.state.values = self.integrator.y
        #self.update_state_from_list(self.state, self.integrator.y)

    def _update(self):
        self._N_H = self._H # reset to Hamiltonian with all parameters unset
        # 
        # Update raw numerical constants first then update functions
        # Less hacky way to do this?
        function_keyval_pairs = []
        for key, val in self._H_params.items(): 
            if isinstance(val,float):
                self._N_H = self._N_H.subs(key, val)
            else:
                function_keyval_pairs.append((key,val)) 
        for keyval in function_keyval_pairs:
            self._N_H = self._N_H.subs(keyval[0],keyval[1])
        
        qp_vars = self.qp_vars
        self._Energy = lambdify(qp_vars,self._N_H,**_lambdify_kwargs)
        self._derivs = {}
        self._N_derivs = []
        flow = []
        Nflow = []
        for v in self.qp_vars:
            deriv = self.Lie_deriv(v)
            Nderiv = self.N_Lie_deriv(v)
            self._derivs[v] = self.N_Lie_deriv(v)
            flow.append(deriv)
            Nflow.append(Nderiv)

        N_dim = 2*self.N_dof
        self._flow = Matrix(flow)
        self._jac = Matrix(N_dim,N_dim, lambda i,j: diff(flow[i],qp_vars[j]))

        # is this used anywhere?
        self._N_derivs = [lambdify(qp_vars,fun,**_lambdify_kwargs) for fun in Nflow]
        self._Nflow = lambdify(qp_vars,Nflow,**_lambdify_kwargs)
        NjacMtrx = Matrix(N_dim,N_dim, lambda i,j: diff(Nflow[i],qp_vars[j]))
        self._Njac = lambdify(qp_vars,NjacMtrx,**_lambdify_kwargs)
        self._integrator = ode(
                lambda t,y: self._Nflow(*y),
                jac = lambda t,y: self._Njac(*y))
        self._integrator.set_integrator('dop853')# ('lsoda') #
        self._integrator.set_initial_value(self.state.values)
        self._needs_update=False

def reduce_hamiltonian(ham):
    state = ham.state
    new_params = ham.H_params.copy()
    #pq_val_rule = ham.state.as_rule()
    #new_pq_pairs= []
    untracked_q, untracked_p = [], []
    new_q, new_p = [], []
    new_qvals, new_pvals = [], []
    qp_pairs = [(state.qp_vars[i], state.qp_vars[i+state.N_dof]) for i in range(state.N_dof)]
    for qp_pair in qp_pairs:
        q,p = qp_pair
        pval,qval = state.qp[p],state.qp[q]
        if q not in ham.H.free_symbols or p not in ham.H.free_symbols: # if q is cyclic, p is conserved and we ignore that dof
            untracked_q.append(q)
            untracked_p.append(p)
            new_params[q] = qval
            new_params[p] = pval
        else:
            new_q.append(q)
            new_p.append(p)
            new_qvals.append(qval)
            new_pvals.append(pval)
    new_vals = np.array(new_qvals + new_pvals)
    new_qp_vars = new_q + new_p
    untracked_qp_vars = untracked_q + untracked_p
    new_state = PhaseSpaceState(new_qp_vars, new_vals,state.t)
    new_ham = Hamiltonian(ham.H,new_params,new_state, full_qp_vars = ham.full_qp_vars)
    return new_ham
