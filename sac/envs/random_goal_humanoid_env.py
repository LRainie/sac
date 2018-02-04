"""Implements humanoid env which is sparsely rewarded for reaching a goal"""

import numpy as np
from rllab.core.serializable import Serializable
from rllab.envs.mujoco.humanoid_env import HumanoidEnv
from rllab.misc.overrides import overrides
from rllab.envs.base import Step
from rllab.envs.mujoco.mujoco_env import MujocoEnv
from rllab.misc import logger, autoargs

from .helpers import random_point_on_circle, log_random_goal_progress

REWARD_TYPES = ('dense', 'sparse')

class RandomGoalHumanoidEnv(HumanoidEnv):
    """Implements humanoid env that is sparsely rewarded for reaching a goal"""

    @autoargs.arg('vel_deviation_cost_coeff', type=float,
                  help='cost coefficient for velocity deviation')
    @autoargs.arg('alive_bonus', type=float,
                  help='bonus reward for being alive')
    @autoargs.arg('ctrl_cost_coeff', type=float,
                  help='cost coefficient for control inputs')
    @autoargs.arg('impact_cost_coeff', type=float,
                  help='cost coefficient for impact')
    def __init__(self,
                 reward_type='dense',
                 terminate_at_goal=True,
                 goal_reward_weight=1e-3,
                 goal_radius=0.25,
                 goal_distance=5,
                 goal_angle_range=(0, 2*np.pi),
                 vel_deviation_cost_coeff=1e-2,
                 alive_bonus=0.2,
                 ctrl_cost_coeff=1e-3,
                 impact_cost_coeff=1e-5,
                 *args,
                 **kwargs):
        assert reward_type in REWARD_TYPES

        self._reward_type = reward_type
        self.terminate_at_goal = terminate_at_goal

        self.goal_reward_weight = goal_reward_weight
        self.goal_radius = goal_radius
        self.goal_distance = goal_distance
        self.goal_angle_range = goal_angle_range

        self.vel_deviation_cost_coeff = vel_deviation_cost_coeff
        self.alive_bonus = alive_bonus
        self.ctrl_cost_coeff = ctrl_cost_coeff
        self.impact_cost_coeff = impact_cost_coeff

        MujocoEnv.__init__(self, *args, **kwargs)
        Serializable.quick_init(self, locals())

    def reset(self, goal_position=None, *args, **kwargs):
        if goal_position is None:
            goal_position = random_point_on_circle(
                angle_range=self.goal_angle_range,
                radius=self.goal_distance)

        self.goal_position = goal_position

        return super().reset(*args, **kwargs)

    def get_current_obs(self):
        proprioceptive_observation = super().get_current_obs()
        exteroceptive_observation = self.goal_position

        observation = np.concatenate(
            [proprioceptive_observation,
             exteroceptive_observation]
        ).reshape(-1)

        return observation

    @overrides
    def step(self, action):
        self.forward_dynamics(action)

        xy_position = self.get_body_com('torso')[:2]
        self.goal_distance = np.linalg.norm(xy_position - self.goal_position)

        goal_reached = self.goal_distance < self.goal_radius

        if self._reward_type == 'dense':
            goal_reward = -self.goal_distance * self.goal_reward_weight
        elif self._reward_type == 'sparse':
            goal_reward = int(goal_reached) * self.goal_reward_weight




        if self.ctrl_cost_coeff > 0:
            lb, ub = self.action_bounds
            scaling = (ub - lb) * 0.5
            ctrl_cost = 0.5 * self.ctrl_cost_coeff * np.sum(
                np.square(action / scaling))
        else:
            ctrl_cost = 0.0

        if self.impact_cost_coeff > 0:
            cfrc_ext = self.model.data.cfrc_ext
            impact_cost = 0.5 * self.impact_cost_coeff * np.sum(
                np.square(np.clip(cfrc_ext, -1, 1)))
        else:
            impact_cost = 0.0

        if self.vel_deviation_cost_coeff > 0:
            comvel = self.get_body_comvel("torso")
            vel_deviation_cost = 0.5 * self.vel_deviation_cost_coeff * np.sum(
                np.square(comvel[2:]))


        reward = (goal_reward + self.alive_bonus
                  - ctrl_cost - impact_cost - vel_deviation_cost)

        is_healthy = 0.2 < self.model.data.qpos[2] < 0.8
        done = not is_healthy or (self.terminate_at_goal and goal_reached)

        next_observation = self.get_current_obs()
        info = {'goal_position': self.goal_position}
        return Step(next_observation, reward, done, **info)

    @overrides
    def log_diagnostics(self, paths, *args, **kwargs):
        log_random_goal_progress(paths)
