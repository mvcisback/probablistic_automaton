"""Code for modeling a probablistic automaton."""

import random
from collections import defaultdict
from typing import Callable, Hashable, Mapping, Set

import attr
import funcy as fn
from dfa import DFA, SupAlphabet, ProductAlphabet
from dfa.dfa import Alphabet, Letter, State

Action = Letter


@attr.s(frozen=True, auto_attribs=True)
class Distribution:
    """Object representing a discrete Distribution over environment actions."""
    _dist: Mapping[Action, float]

    def sample(self) -> Action:
        """Sample an envionment action."""
        actions, weights = zip(*self._dist.items())
        return random.choices(actions, weights)[0]

    def __call__(self, action):
        """Evaluates the probability of an action."""
        return self._dist.get(action, 0)

    def items(self):
        """Sequence of Action, Probability pairs defining the distribution."""
        return self._dist.items()


EnvDist = Callable[[State, Action], Distribution]


def uniform(actions: Set[Action]) -> EnvDist:
    """
    Encodes an environment that selects actions uniformly at random,
    i.e., maps all state/action combinations to a Uniform distribution
    of the input (environment) actions.
    """
    size = len(actions)
    dist = Distribution({a: 1/size for a in actions})
    return lambda *_: dist


def _dict2dist(env_dist) -> EnvDist:
    @fn.memoize
    def env_dist2(state, action):
        dist = env_dist(state, action)
        if isinstance(dist, Distribution):
            return dist

        return Distribution(dist)

    return env_dist2


@attr.s(frozen=True, auto_attribs=True)
class PDFA:
    """A DFA over a product alphabet where the first value
    is non-deterministic and the second value is set according
    to a state indexed stationary distribution.
    """
    dfa: DFA = attr.ib()
    env_dist: EnvDist = attr.ib(converter=_dict2dist)

    @dfa.validator
    def _check_product_lang(self, _, dfa):
        assert all(isinstance(i, tuple) and len(i) == 2 for i in dfa.inputs)

    @property
    def env_inputs(self):
        """Accesses the set of environment inputs."""
        return set(fn.pluck(1, self.dfa.inputs))

    @property
    def inputs(self):
        """Accesses the set of (non-environment) inputs."""
        return set(fn.pluck(0, self.dfa.inputs))

    @property
    def outputs(self):
        """Accesses the set of possible outputs."""
        return self.dfa.outputs

    @property
    def start(self):
        """Accesses the start state."""
        return self.dfa.start

    def states(self):
        """Computes the set of reachable states from start."""
        return self.dfa.states()

    def run(self, *, start=None, seed=None):
        """Co-routine interface for simulating runs of the automaton.

        - Users can send system actions (elements of self.inputs).
        - Co-routine yields the current state.

        Example:
        =======

        machine: PDFA = ..
        my_input: Action = ..            # Element of machine.inputs.

        sim = machine.run()              # Start co-routine.

        state1 = sim.send(my_input)
        state2 = sim.send(my_input)
        """

        if seed is not None:
            random.seed(seed)

        state = self.start if start is None else start
        machine = self.dfa.run(start=start)

        while True:
            sys_action = yield state
            env_action = self.env_dist(state, sys_action).sample()
            state = machine.send((sys_action, env_action))

    @fn.memoize
    def support(self, state, action) -> Set[State]:
        """Returns the set of reachable states given (state, action)."""
        return set(self.transition_probs(state, action).keys())

    def _probs(self, start, action):
        for e, p in self.env_dist(start, action).items():
            end = self.dfa._transition(start, (action, e))
            yield (end, p)

    def transition_probs(self, state, action) -> Mapping[State, float]:
        """Returns distribution over states given (state, action)"""
        probs = defaultdict(lambda: 0)
        for end, prob in self._probs(state, action):
            probs[end] += prob
        return probs

    def prob(self, start: State, end: State, action: Action) -> float:
        """
        Returns the probability of transitioning from start to end
        given action.
        """
        return sum(p for s, p in self._probs(start, action) if s == end)


def pdfa(
        start: State,
        label: Callable[[State], Letter],
        transition: Callable[[State, Action], State],
        env_dist: EnvDist,
        inputs: Alphabet = None,
        env_inputs: Alphabet = None,
        outputs: Alphabet = None
) -> PDFA:
    """Main entrypoint for construction a Probablistic Automaton."""

    if inputs is None:
        inputs = SupAlphabet()
    if outputs is None:
        outputs = {True, False}
    if env_inputs is None:
        env_inputs = {None}

    inputs = ProductAlphabet(inputs, env_inputs)

    return PDFA(
        env_dist=env_dist,
        dfa=DFA(
            start=start, label=label,
            inputs=inputs, outputs=outputs,
            transition=transition,
        ),
    )


def lift(dyn: DFA) -> PDFA:
    """Lifts a DFA into a deterministic PDFA."""
    return PDFA(
        dfa=attr.evolve(
            dyn,
            inputs=ProductAlphabet(dyn.inputs, {None}),
            transition=lambda s, c: dyn._transition(s, c[0]),
        ),
        env_dist=uniform({None}),
    )


def randomize(dyn: DFA) -> PDFA:
    """Lifts a DFA into a PDFA where original inputs are applied
    uniformly at random.
    """
    return PDFA(
        dfa=attr.evolve(
            dyn,
            inputs=ProductAlphabet({None}, dyn.inputs),
            transition=lambda s, c: dyn._transition(s, c[1]),
        ),
        env_dist=uniform(dyn.inputs),
    )
