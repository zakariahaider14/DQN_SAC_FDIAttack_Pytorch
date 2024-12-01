# !#Testing with WAC
import torch
import csv
from datetime import datetime
from stable_baselines3.common.callbacks import CheckpointCallback, EvalCallback
import json
import numpy as np
import torch.nn as nn
import torch.optim as optim
import torch.nn.functional as F
import torch.autograd as autograd
import torch.cuda as cuda
import traceback
import functools


import matplotlib.pyplot as plt
import gymnasium as gym
from stable_baselines3 import SAC, DQN

from DiscreteHybridEnv import DiscreteHybridEnv
from combined_pinn import CompetingHybridEnv



import os
import tempfile
import sys

# Set a different temporary directory
os.environ['TMPDIR'] = tempfile.gettempdir()
os.environ['TORCH_HOME'] = tempfile.gettempdir()

# Disable PyTorch's JIT compilation
os.environ['PYTORCH_JIT'] = '0'

from stable_baselines3 import SAC
from stable_baselines3.common.vec_env import DummyVecEnv

import torch
torch.set_num_threads(1)

import torch
torch.set_num_threads(1)

from datetime import datetime  # Change this line

# ... existing code ...
current_time = datetime.now().strftime("%Y%m%d_%H%M%S") 

log_file = f"logs/training_log_{current_time}.txt"

# Create a custom logger class
class Logger(object):
    def __init__(self, filename):
        self.terminal = sys.stdout
        self.log = open(filename, 'w', encoding='utf-8')

    def write(self, message):
        self.terminal.write(message)
        self.log.write(message)
        self.log.flush()

    def flush(self):
        self.terminal.flush()
        self.log.flush()

# Redirect stdout to both terminal and file
sys.stdout = Logger(log_file)

# import shimmy
# Check if TensorFlow can see the GPU
print("Num GPUs Available: ", torch.cuda.device_count())

device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
print(f"Using device: {device}")




# System Constants
NUM_BUSES = 33
NUM_EVCS = 5
EVCS_BUSES = [4, 10, 15, 20, 25]  # 0-based indexing

# Base Values
S_BASE = 10e6      # VA
V_BASE_HV = 12660  # V
V_BASE_LV = 800    # V
V_BASE_DC = 800    # V


# Calculate base currents and impedances
I_BASE_HV = S_BASE / (np.sqrt(3) * V_BASE_HV)
I_BASE_LV = S_BASE / (np.sqrt(3) * V_BASE_LV)
I_BASE_DC = S_BASE / V_BASE_DC
Z_BASE_HV = V_BASE_HV**2 / S_BASE
Z_BASE_LV = V_BASE_LV**2 / S_BASE


# EVCS Parameters
EVCS_CAPACITY = 80e3 / S_BASE  # 80 kW in per-unit
EVCS_EFFICIENCY = 0.98
EVCS_VOLTAGE = V_BASE_DC / V_BASE_LV  # In p.u.

GRID_VOLTAGE = 12600  # 12.6 kV


V_OUT_NOMINAL = EVCS_VOLTAGE  # Nominal output voltage in p.u.
V_OUT_VARIATION = 0.05  # 5% allowed variation


# Controller Parameters
EVCS_PLL_KP = 0.1
EVCS_PLL_KI = 0.2
MAX_PLL_ERROR = 5.0

EVCS_OUTER_KP = 0.5 #0.5 and 0.3 was original value
EVCS_OUTER_KI = 0.3

EVCS_INNER_KP = 0.5
EVCS_INNER_KI = 0.3
OMEGA_N = 2 * torch.pi * 60  # Nominal angular frequency (60 Hz)

# Wide Area Controller Parameters
WAC_KP_VDC = 0.1
WAC_KI_VDC = 0.05

WAC_KP_VOUT = 0.1
WAC_KI_VOUT = 0.05 # original value is 0.5
WAC_VOLTAGE_SETPOINT = V_BASE_DC / V_BASE_LV  # Desired DC voltage in p.u.
WAC_VOUT_SETPOINT = V_BASE_DC / V_BASE_LV  # Desired output voltage in p.u.


# Other Parameters
CONSTRAINT_WEIGHT = 1.0
LCL_L1 = 0.001 / Z_BASE_LV  # Convert to p.u.
LCL_L2 = 0.001 / Z_BASE_LV  # Convert to p.u.
LCL_CF = 10e-1 * S_BASE / (V_BASE_LV**2)  # Convert to p.u.
R = 0.01 / Z_BASE_LV  # Convert to p.u.
C_dc = 0.01 * S_BASE / (V_BASE_LV**2)  # Convert to p.u.    


L_dc = 0.001 / Z_BASE_LV  # Convert to p.u.
v_battery = 800 / V_BASE_DC  # Convert to p.u.
R_battery = 0.01 / Z_BASE_LV  # Convert to p.u.

# Time parameters
TIME_STEP = 0.1 # 1 ms
TOTAL_TIME = 10000  # 100 seconds

# Load IEEE 33-bus system data
line_data = [
    (1, 2, 0.0922, 0.0477), (2, 3, 0.493, 0.2511), (3, 4, 0.366, 0.1864), (4, 5, 0.3811, 0.1941),
    (5, 6, 0.819, 0.707), (6, 7, 0.1872, 0.6188), (7, 8, 1.7114, 1.2351), (8, 9, 1.03, 0.74),
    (9, 10, 1.04, 0.74), (10, 11, 0.1966, 0.065), (11, 12, 0.3744, 0.1238), (12, 13, 1.468, 1.155),
    (13, 14, 0.5416, 0.7129), (14, 15, 0.591, 0.526), (15, 16, 0.7463, 0.545), (16, 17, 1.289, 1.721),
    (17, 18, 0.732, 0.574), (2, 19, 0.164, 0.1565), (19, 20, 1.5042, 1.3554), (20, 21, 0.4095, 0.4784),
    (21, 22, 0.7089, 0.9373), (3, 23, 0.4512, 0.3083), (23, 24, 0.898, 0.7091), (24, 25, 0.896, 0.7011),
    (6, 26, 0.203, 0.1034), (26, 27, 0.2842, 0.1447), (27, 28, 1.059, 0.9337), (28, 29, 0.8042, 0.7006),
    (29, 30, 0.5075, 0.2585), (30, 31, 0.9744, 0.963), (31, 32, 0.31, 0.3619), (32, 33, 0.341, 0.5302)
]

bus_data = np.array([
    [1, 0, 0, 0], [2, 100, 60, 0], [3, 70, 40, 0], [4, 120, 80, 0], [5, 80, 30, 0],
    [6, 60, 20, 0], [7, 145, 100, 0], [8, 160, 100, 0], [9, 60, 20, 0], [10, 60, 20, 0],
    [11, 100, 30, 0], [12, 60, 35, 0], [13, 60, 35, 0], [14, 80, 80, 0], [15, 100, 10, 0],
    [16, 100, 20, 0], [17, 60, 20, 0], [18, 90, 40, 0], [19, 90, 40, 0], [20, 90, 40, 0],
    [21, 90, 40, 0], [22, 90, 40, 0], [23, 90, 40, 0], [24, 420, 200, 0], [25, 380, 200, 0],
    [26, 100, 25, 0], [27, 60, 25, 0], [28, 60, 20, 0], [29, 120, 70, 0], [30, 200, 600, 0],
    [31, 150, 70, 0], [32, 210, 100, 0], [33, 60, 40, 0]
])

bus_data[:, 1:3] = bus_data[:, 1:3]*1e3 / S_BASE
EVCS_CAPACITY = 80e3 / S_BASE    # Convert kW to per-unit


# Update Y-bus matrix initialization
Y_bus = torch.zeros((NUM_BUSES, NUM_BUSES), dtype=torch.complex64)

# Fill Y-bus matrix with complex values
for line in line_data:
    from_bus, to_bus, r, x = line
    from_bus, to_bus = int(from_bus)-1, int(to_bus)-1  # Convert to 0-based index
    z = complex(r, x)
    y = 1.0 / z
    Y_bus[from_bus, from_bus] += y
    Y_bus[to_bus, to_bus] += y
    Y_bus[from_bus, to_bus] -= y
    Y_bus[to_bus, from_bus] -= y

# Convert Y_bus to torch tensor and ensure it's complex
Y_bus_torch = torch.as_tensor(Y_bus, dtype=torch.complex64)


G_d = None
G_q = None

def initialize_conductance_matrices():
    """Initialize conductance matrices from Y-bus matrix"""
    global G_d, G_q, B_d, B_q
    
    # Ensure Y_bus_torch is complex
    Y_bus_complex = Y_bus_torch.to(torch.complex64)
    
    # Extract G (conductance) and B (susceptance) matrices
    G_d = torch.real(Y_bus_complex).to(torch.float32)  # Real part for d-axis
    G_q = torch.real(Y_bus_complex).to(torch.float32)  # Real part for q-axis
    B_d = torch.imag(Y_bus_complex).to(torch.float32)  # Imaginary part for d-axis
    B_q = torch.imag(Y_bus_complex).to(torch.float32)  # Imaginary part for q-axis
    
    return G_d, G_q, B_d, B_q

# Call this function before training starts
G_d, G_q, B_d, B_q = initialize_conductance_matrices()

# For individual elements (if needed)
G_d_kh = torch.diag(G_d)  # Diagonal elements for d-axis conductance
G_q_kh = torch.diag(G_q)  # Diagonal elements for q-axis conductance
B_d_kh = torch.diag(B_d)  # Diagonal elements for d-axis susceptance
B_q_kh = torch.diag(B_q)  # Diagonal elements for q-axis susceptance




class SACWrapper(gym.Env):
    def __init__(self, env, agent_type, dqn_agent=None, sac_defender=None, sac_attacker=None):
        super(SACWrapper, self).__init__()
        
        self.env = env
        self.agent_type = agent_type
        self.dqn_agent = dqn_agent
        self.sac_defender = sac_defender
        self.sac_attacker = sac_attacker
        self.NUM_EVCS = env.NUM_EVCS
        
        # Initialize tracking variables as instance variables using PyTorch tensors
        self.voltage_deviations = torch.zeros(self.NUM_EVCS, dtype=torch.float32)
        self.cumulative_deviation = torch.tensor(0.0, dtype=torch.float32)
        self.attack_active = False
        self.target_evcs = torch.zeros(self.NUM_EVCS)
        self.attack_duration = torch.tensor(0.0, dtype=torch.float32)
        self.state = torch.zeros(env.observation_space.shape[0], dtype=torch.float32)
        
        # Set action spaces
        self.observation_space = env.observation_space
        if agent_type == 'attacker':
            self.action_space = env.sac_attacker_action_space
        else:
            self.action_space = env.sac_defender_action_space

    def decode_dqn_action(self, action):
        """Decode DQN action by delegating to the underlying environment."""
        if hasattr(self.env, 'decode_dqn_action'):
            return self.env.decode_dqn_action(action)
        return int(action)  # Fallback default decoding

    def step(self, action):
        try:
            with torch.no_grad():  # Wrap everything in no_grad
                # Store current state of tracking variables
                current_tracking = {
                    'voltage_deviations': self.voltage_deviations.detach().clone(),
                    'cumulative_deviation': self.cumulative_deviation.detach().clone(),
                    'attack_active': self.attack_active,
                    'target_evcs': self.target_evcs.detach().clone(),
                    'attack_duration': self.attack_duration.detach().clone()
                }

                # Process state and actions
                state_numpy = self.state.detach().cpu().numpy() if torch.is_tensor(self.state) else self.state
                
                # Get DQN action and ensure proper formatting
                dqn_state = torch.as_tensor(state_numpy, device='cpu').reshape(1, -1)
                dqn_raw = self.dqn_agent.predict(dqn_state.numpy(), deterministic=True)
                dqn_action = dqn_raw[0] if isinstance(dqn_raw, tuple) else dqn_raw
                
                # Ensure dqn_action is properly formatted before decoding
                if isinstance(dqn_action, np.ndarray) and dqn_action.size == 1:
                    dqn_action = int(dqn_action.item())
                
                # Decode action using the updated method
                decoded_dqn_action = self.env.decode_action(dqn_action)
                
                # Get agent actions
                if self.agent_type == 'attacker':
                    attacker_action = action
                    defender_action = (
                        self.sac_defender.predict(state_numpy, deterministic=True)[0]
                        if self.sac_defender is not None 
                        else np.zeros(self.NUM_EVCS * 2)
                    )
                else:
                    defender_action = action
                    attacker_action = (
                        self.sac_attacker.predict(state_numpy, deterministic=True)[0]
                        if self.sac_attacker is not None 
                        else np.zeros(self.NUM_EVCS * 2)
                    )
                
                # Combine actions (all in numpy)
                combined_action = {
                    'dqn': decoded_dqn_action,
                    'attacker': attacker_action,
                    'defender': defender_action
                }
                
                # Take step
                next_state, rewards, done, truncated, info = self.env.step(combined_action)
                
                # Update state and tracking variables (convert to tensors)
                self.state = torch.as_tensor(next_state, dtype=torch.float32, device='cpu')
                info_dict = info if isinstance(info, dict) else {}
                
                # Update instance variables
                self.voltage_deviations = torch.as_tensor(
                    info_dict.get('voltage_deviations', np.zeros(self.NUM_EVCS)), 
                    dtype=torch.float32, 
                    device= device
                )
                self.cumulative_deviation = torch.tensor(
                    float(info_dict.get('cumulative_deviation', 0.0)), 
                    dtype=torch.float32, 
                    device=device
                )
                self.attack_active = bool(info_dict.get('attack_active', False))
                self.target_evcs = torch.as_tensor(
                    info_dict.get('target_evcs', np.zeros(self.NUM_EVCS)), 
                    device=device
                )
                self.attack_duration = torch.tensor(
                    float(info_dict.get('attack_duration', 0.0)), 
                    dtype=torch.float32, 
                    device=device
                )
                
                reward = float(rewards[self.agent_type] if isinstance(rewards, dict) else rewards)
                
                return self.state, reward, done, truncated, info
                
        except Exception as e:
            print(f"Error in SACWrapper step: {e}")
            return self.state.detach().cpu().numpy(), 0.0, True, False, current_tracking

    def update_agents(self, dqn_agent=None, sac_defender=None, sac_attacker=None):
        """Update the agents used by the wrapper."""
        if dqn_agent is not None:
            self.dqn_agent = dqn_agent
            print("Updated DQN agent")
        if sac_defender is not None:
            self.sac_defender = sac_defender
            print("Updated SAC defender")
        if sac_attacker is not None:
            self.sac_attacker = sac_attacker
            print("Updated SAC attacker")

    def render(self):
        """Render the environment."""
        return self.env.render()

    def close(self):
        """Close the environment."""
        return self.env.close()

    def reset(self, seed=None, options=None):
        """Reset the environment."""
        try:
            # Reset the environment
            obs_info = self.env.reset(seed=seed)
            
            # Handle different return formats
            if isinstance(obs_info, tuple):
                obs, info = obs_info
            else:
                obs = obs_info
                info = {}
            
            # Convert observation to torch tensor
            self.state = torch.as_tensor(obs, dtype=torch.float32)
            
            # Reset tracking variables
            self.voltage_deviations = torch.zeros(self.NUM_EVCS, dtype=torch.float32)
            self.cumulative_deviation = torch.tensor(0.0, dtype=torch.float32)
            self.attack_active = False
            self.target_evcs = torch.zeros(self.NUM_EVCS)
            self.attack_duration = torch.tensor(0.0, dtype=torch.float32)
            
            # Return observation and info dict according to Gym API
            return self.state, info
            
        except Exception as e:
            print(f"Error in SACWrapper reset: {e}")
            
            # Return zero observation and empty info on error
            self.state = torch.zeros(self.observation_space.shape[0], dtype=torch.float32)
            return self.state, {
                'error': str(e),
                'voltage_deviations': self.voltage_deviations,
                'cumulative_deviation': self.cumulative_deviation,
                'attack_active': self.attack_active,
                'target_evcs': self.target_evcs,
                'attack_duration': self.attack_duration
            }



class EVCS_PowerSystem_PINN(nn.Module):
    def __init__(self):
        super().__init__()
        
        # Initialize layers
        self.dense1 = nn.Linear(1, 256)
        
        # LSTM layers
        self.lstm1 = nn.LSTM(
            input_size=256,
            hidden_size=512,
            batch_first=True,
            bidirectional=False
        )
        
        self.lstm2 = nn.LSTM(
            input_size=512,
            hidden_size=512,
            batch_first=True,
            bidirectional=False
        )
        
        self.lstm3 = nn.LSTM(
            input_size=512,
            hidden_size=512,
            batch_first=True,
            bidirectional=False
        )
        
        self.lstm4 = nn.LSTM(
            input_size=512,
            hidden_size=512,
            batch_first=True,
            bidirectional=False
        )
        
        # Output layer
        self.output_layer = nn.Linear(512, NUM_BUSES * 2 + NUM_EVCS * 18)
        
        # Initialize weights using Xavier/Glorot initialization
        self._init_weights()
        
        # Initialize with a dummy input
        with torch.no_grad():
            dummy_input = torch.zeros((1, 1))
            self.forward(dummy_input)
    
    def _init_weights(self):
        """Initialize weights using Xavier/Glorot initialization"""
        for name, param in self.named_parameters():
            if 'weight' in name:
                nn.init.xavier_normal_(param)
            elif 'bias' in name:
                nn.init.zeros_(param)

    def get_state(self, t):
        """Extract state information from model outputs"""
        outputs = self.forward(t)
        
        # Extract components
        v_d = outputs[:, :NUM_BUSES]
        v_q = outputs[:, NUM_BUSES:2*NUM_BUSES]
        evcs_vars = outputs[:, 2*NUM_BUSES:]
        
        # Create state vector
        state = torch.cat([
            v_d,  # Voltage d-axis components
            v_q,  # Voltage q-axis components
            torch.sqrt(v_d**2 + v_q**2),  # Voltage magnitudes
            evcs_vars  # EVCS-specific variables
        ], dim=1)
        
        return state

    def forward(self, t):
        # Initial transformation with tanh activation
        x = torch.tanh(self.dense1(t))
        
        # Reshape for LSTM (batch_size, timesteps, features)
        x = x.unsqueeze(1)  # Add timestep dimension
        
        # LSTM processing
        x, _ = self.lstm1(x)
        x, _ = self.lstm2(x)
        x, _ = self.lstm3(x)
        x, _ = self.lstm4(x)
        
        # Take the last output from LSTM sequence
        x = x[:, -1, :]
        
        # Output layer
        output = self.output_layer(x)
        
        # Split output into different components
        voltage_magnitude = output[:, :NUM_BUSES]
        voltage_angle = output[:, NUM_BUSES:2*NUM_BUSES]
        evcs_outputs = output[:, 2*NUM_BUSES:]
        
        # Apply appropriate activations
        voltage_magnitude = torch.exp(voltage_magnitude)  # Ensure positive voltage magnitudes
        voltage_angle = torch.atan(voltage_angle)        # Bound angles
        evcs_outputs = torch.tanh(evcs_outputs)         # Bound EVCS outputs
        
        # Concatenate outputs
        return torch.cat([voltage_magnitude, voltage_angle, evcs_outputs], dim=1)

def safe_op(x):
    """Safe operation handling for tensors with proper gradient handling"""
    class SafeFunction(torch.autograd.Function):
        @staticmethod
        def forward(ctx, input_tensor):
            ctx.save_for_backward(input_tensor)
            return torch.where(torch.isfinite(input_tensor), 
                             input_tensor, 
                             torch.zeros_like(input_tensor) + 1e-30)

        @staticmethod
        def backward(ctx, grad_output):
            input_tensor, = ctx.saved_tensors
            return torch.where(torch.isfinite(grad_output), 
                             grad_output, 
                             torch.zeros_like(grad_output) + 1e-30)

    return SafeFunction.apply(x)



def safe_matrix_operations(func):
    """Decorator for safe matrix operations with logging"""
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            result = func(*args, **kwargs)
            # Handle tuple return type properly
            if isinstance(result, tuple):
                nan_check = any([torch.any(torch.isnan(r)) for r in result])
                if nan_check:
                    print(f"Warning: NaN detected in {func.__name__}")
                    print(f"Input shapes: {[arg.shape for arg in args]}")
                    return tuple(torch.zeros_like(r) for r in result)
                return result
            else:
                if torch.any(torch.isnan(result)):
                    print(f"Warning: NaN detected in {func.__name__}")
                    print(f"Input shapes: {[arg.shape for arg in args]}")
                    return torch.zeros_like(result)
                return result
        except Exception as e:
            print(f"Error in {func.__name__}: {str(e)}")
            batch_size = args[0].shape[0]
            num_buses = args[0].shape[1]
            return (torch.zeros((batch_size, num_buses)), torch.zeros((batch_size, num_buses)), {})
    return wrapper

def calculate_power_flow_base(v_d, v_q, G, B, bus_mask):
    """Base power flow calculation with proper shape handling."""
    try:
        # Ensure inputs are rank 2 [batch_size, num_buses]
        v_d = v_d.reshape(-1, v_d.shape[-1])  # [batch, buses]
        v_q = v_q.reshape(-1, v_q.shape[-1])  # [batch, buses]
        
        # Matrix multiplication for power calculations
        # P = V_d * (G * V_d + B * V_q) + V_q * (G * V_q - B * V_d)
        G_vd = torch.matmul(G, v_d.unsqueeze(-1))  # [buses, batch, 1]
        G_vq = torch.matmul(G, v_q.unsqueeze(-1))  # [buses, batch, 1]
        B_vd = torch.matmul(B, v_d.unsqueeze(-1))  # [buses, batch, 1]
        B_vq = torch.matmul(B, v_q.unsqueeze(-1))  # [buses, batch, 1]
        
        # Calculate P and Q
        P = v_d * G_vd.squeeze(-1) + v_q * G_vq.squeeze(-1)  # [batch, buses]
        Q = v_d * B_vd.squeeze(-1) - v_q * B_vq.squeeze(-1)  # [batch, buses]
        
        # Apply mask
        P = P * bus_mask  # [batch, buses]
        Q = Q * bus_mask  # [batch, buses]
        
        # Check shapes
        assert P.shape[0] == Q.shape[0], "Batch dimensions must match"
        assert P.shape[1] == Q.shape[1], "Bus dimensions must match"
        
        return P, Q
        
    except Exception as e:
        print("\nERROR in calculate_power_flow_base:")
        print(str(e))
        print("Error type:", type(e).__name__)
        return None, None, {}

def calculate_power_flow_pcc(v_d, v_q, G, B):
    """PCC power flow calculation."""
    num_buses = v_d.shape[-1]
    mask = torch.cat([torch.tensor([1.0]), torch.zeros(num_buses - 1)], dim=0)
    mask = mask.unsqueeze(0)  # [1, num_buses]
    if v_d.is_cuda:
        mask = mask.cuda()
    return calculate_power_flow_base(v_d, v_q, G, B, mask)

def calculate_power_flow_load(v_d, v_q, G, B):
    """Load bus power flow calculation."""
    num_buses = v_d.shape[-1]
    mask = torch.ones(1, num_buses)
    if v_d.is_cuda:
        mask = mask.cuda()
    # Zero out PCC bus
    mask[0, 0] = 0.0
    # Zero out EVCS buses
    for bus in EVCS_BUSES:
        mask[0, bus] = 0.0
    return calculate_power_flow_base(v_d, v_q, G, B, mask)

def calculate_power_flow_ev(v_d, v_q, G, B):
    """EV bus power flow calculation."""
    num_buses = v_d.shape[-1]
    mask = torch.zeros(1, num_buses)
    if v_d.is_cuda:
        mask = mask.cuda()
    # Set EVCS buses to 1
    for bus in EVCS_BUSES:
        mask[0, bus] = 1.0
    return calculate_power_flow_base(v_d, v_q, G, B, mask)

def physics_loss(model, t, Y_bus_torch, bus_data, attack_actions, defend_actions):
    """Calculate physics-based losses with proper gradient handling."""
    try:
        # Convert inputs to tensors with gradients enabled
        t = torch.tensor(t, dtype=torch.float32, requires_grad=True)
        # Handle Y_bus complex components separately
        # Convert Y_bus to complex tensor properly
        Y_bus_real = Y_bus_torch.real.clone().to(torch.float32)
        Y_bus_imag = Y_bus_torch.imag.clone().to(torch.float32)
        Y_bus_torch = torch.complex(Y_bus_real, Y_bus_imag)

        # Ensure attack and defend actions are proper tensors with gradients
        attack_actions = torch.tensor(attack_actions, dtype=torch.float32, requires_grad=True)
        defend_actions = torch.tensor(defend_actions, dtype=torch.float32, requires_grad=True)
        
        
        # Extract attack and defense actions
        fdi_voltage = attack_actions[:, :NUM_EVCS].reshape(-1, NUM_EVCS)
        fdi_current_d = attack_actions[:, NUM_EVCS:].reshape(-1, NUM_EVCS)
        KP_VOUT = defend_actions[:, :NUM_EVCS].reshape(-1, NUM_EVCS)
        KI_VOUT = defend_actions[:, NUM_EVCS:].reshape(-1, NUM_EVCS)

        # Get predictions from model with gradient tracking
        with torch.set_grad_enabled(True):
            predictions = model(t)
            
            # Extract predictions and ensure they require gradients
            V = torch.exp(predictions[:, :NUM_BUSES]).requires_grad_(True)
            theta = torch.atan(predictions[:, NUM_BUSES:2*NUM_BUSES]).requires_grad_(True)
            evcs_vars = predictions[:, 2*NUM_BUSES:].requires_grad_(True)
            
            # Calculate voltage components
            v_d = (V * torch.cos(theta)).to(torch.float32)
            v_q = (V * torch.sin(theta)).to(torch.float32)
            
            # Split Y_bus into real and imaginary parts
            G = torch.real(Y_bus_torch).to(torch.float32)
            B = torch.imag(Y_bus_torch).to(torch.float32)
            
            # Calculate power flows
            P_g_pcc, Q_g_pcc = calculate_power_flow_pcc(v_d, v_q, G, B)
            P_g_load, Q_g_load = calculate_power_flow_load(v_d, v_q, G, B)
            P_g_ev_load, Q_g_ev_load = calculate_power_flow_ev(v_d, v_q, G, B)
            
            # Calculate power mismatches
            P_mismatch = P_g_pcc - (P_g_load + P_g_ev_load)
            Q_mismatch = Q_g_pcc - (Q_g_load + Q_g_ev_load)
            
            # Calculate power flow loss
            power_flow_loss = safe_op(torch.mean(P_mismatch**2 + Q_mismatch**2))
            
            # Initialize EVCS losses list and WAC variables
            evcs_loss = []
            wac_error_vdc = torch.zeros_like(t)
            wac_integral_vdc = torch.zeros_like(t)
            wac_error_vout = torch.zeros_like(t)
            wac_integral_vout = torch.zeros_like(t)
            
            # Process each EVCS
            for i, bus in enumerate(EVCS_BUSES):
                try:
                    # Extract EVCS variables
                    evcs = evcs_vars[:, i*18:(i+1)*18]
                    evcs_split = torch.split(evcs, 1, dim=1)
                    v_ac, i_ac, v_dc, i_dc, v_out, i_out, i_L1, i_L2, v_c, soc, delta, omega, phi_d, phi_q, gamma_d, gamma_q, i_d, i_q = evcs_split
                    
                    # Clarke and Park Transformations
                    v_alpha = v_ac
                    v_beta = torch.zeros_like(v_ac)
                    i_alpha = i_ac
                    i_beta = torch.zeros_like(i_ac)
                    v_out = v_out + fdi_voltage[:, i:i+1]
                    i_d = i_d + fdi_current_d[:, i:i+1]
                    
                    v_d_evcs = safe_op(v_alpha * torch.cos(delta) + v_beta * torch.sin(delta))
                    v_q_evcs = safe_op(-v_alpha * torch.sin(delta) + v_beta * torch.cos(delta))
                    i_d_measured = safe_op(i_alpha * torch.cos(delta) + i_beta * torch.sin(delta))
                    i_q_measured = safe_op(-i_alpha * torch.sin(delta) + i_beta * torch.cos(delta))
                    
                    # Apply FDI attacks
                    v_out += fdi_voltage[:, i:i+1]
                    i_d += fdi_current_d[:, i:i+1]
                    
                    # PLL Dynamics
                    v_q_normalized = torch.tanh(safe_op(v_q_evcs))
                    pll_error = safe_op(EVCS_PLL_KP * v_q_normalized + EVCS_PLL_KI * phi_q)
                    pll_error = torch.clamp(pll_error, -MAX_PLL_ERROR, MAX_PLL_ERROR)
                    
                    # Calculate derivatives using autograd
                    ddelta_dt = torch.autograd.grad(delta.sum(), t, create_graph=True)[0] if delta.requires_grad else torch.zeros_like(delta)
                    domega_dt = torch.autograd.grad(omega.sum(), t, create_graph=True)[0] if omega.requires_grad else torch.zeros_like(omega)
                    dphi_d_dt = torch.autograd.grad(phi_d.sum(), t, create_graph=True)[0] if phi_d.requires_grad else torch.zeros_like(phi_d)
                    dphi_q_dt = torch.autograd.grad(phi_q.sum(), t, create_graph=True)[0] if phi_q.requires_grad else torch.zeros_like(phi_q)
                    di_d_dt = torch.autograd.grad(i_d.sum(), t, create_graph=True)[0] if i_d.requires_grad else torch.zeros_like(i_d)
                    di_q_dt = torch.autograd.grad(i_q.sum(), t, create_graph=True)[0] if i_q.requires_grad else torch.zeros_like(i_q)
                    di_L1_dt = torch.autograd.grad(i_L1.sum(), t, create_graph=True)[0] if i_L1.requires_grad else torch.zeros_like(i_L1)
                    di_L2_dt = torch.autograd.grad(i_L2.sum(), t, create_graph=True)[0] if i_L2.requires_grad else torch.zeros_like(i_L2)
                    dv_c_dt = torch.autograd.grad(v_c.sum(), t, create_graph=True)[0] if v_c.requires_grad else torch.zeros_like(v_c)
                    dv_dc_dt = torch.autograd.grad(v_dc.sum(), t, create_graph=True)[0] if v_dc.requires_grad else torch.zeros_like(v_dc)
                    di_out_dt = torch.autograd.grad(i_out.sum(), t, create_graph=True)[0] if i_out.requires_grad else torch.zeros_like(i_out)
                    dsoc_dt = torch.autograd.grad(soc.sum(), t, create_graph=True)[0] if soc.requires_grad else torch.zeros_like(soc)

                    P_ac = safe_op(v_d_evcs * i_d + v_q_evcs * i_q)
                    dv_dc_dt_loss = safe_op(torch.mean((dv_dc_dt - (1/(v_dc * C_dc + 1e-6)) * (P_ac - v_dc * i_dc))**2))

                    modulation_index_vdc = torch.clamp(WAC_KP_VDC * wac_error_vdc + WAC_KI_VDC * wac_integral_vdc, 0, 1)
                    modulation_index_vout = torch.clamp(WAC_KP_VOUT * wac_error_vout + WAC_KI_VOUT * wac_integral_vout, 0, 1)

                    v_out_expected = modulation_index_vout * v_dc
                    v_out_loss = safe_op(torch.mean((v_out - v_out_expected)**2))

                    v_out_lower = V_OUT_NOMINAL * (1 - V_OUT_VARIATION)
                    v_out_upper = V_OUT_NOMINAL * (1 + V_OUT_VARIATION)
                    v_out_constraint = safe_op(torch.mean((torch.relu(v_out_lower - v_out) + torch.relu(v_out - v_out_upper))**2))

                    di_out_dt_loss = safe_op(torch.mean((di_out_dt - (1/L_dc) * (v_out - v_battery - R_battery * i_out))**2))
                    dsoc_dt_loss = safe_op(torch.mean((dsoc_dt - (EVCS_EFFICIENCY * i_out) / (EVCS_CAPACITY + 1e-6))**2))

                    P_dc = safe_op(v_dc * i_dc)
                    P_out = safe_op(v_out * i_out)
                    DC_DC_EFFICIENCY = 0.98
                    power_balance_loss = safe_op(torch.mean((P_dc - P_ac)**2 + (P_out - P_dc * DC_DC_EFFICIENCY)**2))

                    current_consistency_loss = safe_op(torch.mean((i_ac - i_L2)**2 + (i_d - i_d_measured)**2 + (i_q - i_q_measured)**2))

                    # Calculate EVCS losses with safe handling
                    evcs_losses = [
                        safe_op(torch.mean((ddelta_dt - omega)**2)),
                        safe_op(torch.mean((domega_dt - pll_error)**2)),
                        safe_op(torch.mean((dphi_d_dt - v_d_evcs)**2)),
                        safe_op(torch.mean((dphi_q_dt - v_q_evcs)**2)),
                        safe_op(torch.mean((di_d_dt - (1/LCL_L1) * (v_d_evcs - R * i_d))**2)),
                        safe_op(torch.mean((di_q_dt - (1/LCL_L1) * (v_q_evcs - R * i_q))**2)),
                        safe_op(torch.mean((di_L1_dt - (1/LCL_L1) * (v_d_evcs - v_c - R * i_L1))**2)),
                        safe_op(torch.mean((di_L2_dt - (1/LCL_L2) * (v_c - v_ac - R * i_L2))**2)),
                        safe_op(torch.mean((dv_c_dt - (1/LCL_CF) * (i_L1 - i_L2))**2)),
                        safe_op(torch.mean((dv_dc_dt - (1/(v_dc * C_dc + 1e-6)) * (P_ac - v_dc * i_dc))**2)),
                        safe_op(torch.mean((v_out - v_out_expected)**2)),
                        safe_op(torch.mean((di_out_dt - (1/L_dc) * (v_out - v_battery - R_battery * i_out))**2)),
                        safe_op(torch.mean((dsoc_dt - (EVCS_EFFICIENCY * i_out) / (EVCS_CAPACITY + 1e-6))**2)),
                        safe_op(torch.mean((P_dc - P_ac)**2 + (P_out - P_dc * DC_DC_EFFICIENCY)**2)),
                        safe_op(torch.mean((i_ac - i_L2)**2 + (i_d - i_d_measured)**2 + (i_q - i_q_measured)**2))
                    ]
                    
                    evcs_loss.extend(evcs_losses)

                except Exception as e:
                    print(f"Error in EVCS {i} calculations:", e)
                    # Add zero losses if calculation fails
                    evcs_loss.extend([torch.tensor(0.0)] * 15)

            # Calculate final losses with gradient tracking
            power_flow_loss = safe_op(torch.mean(P_mismatch**2 + Q_mismatch**2))
            V_regulation_loss = safe_op(torch.mean((V - torch.ones_like(V))**2))
            evcs_total_loss = safe_op(torch.sum(torch.stack(evcs_loss)))
            wac_loss = safe_op(torch.mean(wac_error_vdc**2 + wac_error_vout**2))
            
            # Combine all losses
            total_loss = power_flow_loss + evcs_total_loss + wac_loss + V_regulation_loss
            
            # Ensure all losses require gradients
            total_loss.requires_grad_(True)
            power_flow_loss.requires_grad_(True)
            evcs_total_loss.requires_grad_(True)
            wac_loss.requires_grad_(True)
            V_regulation_loss.requires_grad_(True)

        return (
            total_loss,
            power_flow_loss,
            evcs_total_loss,
            wac_loss,
            V_regulation_loss
        )
        
    except Exception as e:
        print("\nERROR in physics_loss:")
        print(str(e))
        print("Error type:", type(e).__name__)
        traceback.print_exc()  # Add this to get full traceback
        return (
            torch.tensor(1e6, dtype=torch.float32, requires_grad=True),
            torch.tensor(0.0, dtype=torch.float32),
            torch.tensor(0.0, dtype=torch.float32),
            torch.tensor(0.0, dtype=torch.float32),
            torch.tensor(0.0, dtype=torch.float32)
        )

def safe_op(x):
    """Safely perform operations while maintaining gradients."""
    if torch.is_tensor(x):
        if x.requires_grad:
            return x
        else:
            return x.requires_grad_(True)
    return torch.tensor(x, requires_grad=True)
def train_model(initial_model, dqn_agent, sac_attacker, sac_defender, Y_bus_torch, bus_data, epochs=1500, batch_size=256):
    """Train the PINN model with proper data handling."""
    try:
        model = initial_model
        optimizer = torch.optim.Adam(model.parameters(), lr=1e-3)
        
        # Create environment with necessary data
        env = CompetingHybridEnv(
            pinn_model=model,
            y_bus_torch=Y_bus_torch,
            bus_data=bus_data,
            v_base_lv=V_BASE_DC,
            dqn_agent=dqn_agent,
            num_evcs=NUM_EVCS,
            num_buses=NUM_BUSES,
            time_step=TIME_STEP
        )
        
        # Get bus data from environment
        bus_data_torch = torch.as_tensor(bus_data, dtype=torch.float32)
        Y_bus_torch = Y_bus_torch.to(torch.float32)
        
        history = {
            'total_loss': [],
            'power_flow_loss': [],
            'evcs_loss': [],
            'wac_loss': [],
            'v_reg_loss': []
        }
        
        for epoch in range(epochs):
            try:
                # Reset environment and get initial state
                reset_result = env.reset()
                
                # Handle different return formats from reset()
                if isinstance(reset_result, tuple):
                    state = reset_result[0]  # Extract state from tuple
                else:
                    state = reset_result
                    
                if state is None:
                    print(f"Error: Invalid state in epoch {epoch}")
                    continue
                
                # Ensure state is properly shaped
                state = np.array(state).reshape(1, -1)
                
                # Get actions from agents with proper handling of return values
                try:
                    # DQN action
                    dqn_prediction = dqn_agent.predict(state, deterministic=True)
                    dqn_action = dqn_prediction[0] if isinstance(dqn_prediction, tuple) else dqn_prediction
                    if isinstance(dqn_action, np.ndarray):
                        dqn_action = dqn_action.squeeze()
                    
                    # SAC Attacker action
                    attack_prediction = sac_attacker.predict(state, deterministic=True)
                    attack_action = attack_prediction[0] if isinstance(attack_prediction, tuple) else attack_prediction
                    if isinstance(attack_action, np.ndarray):
                        attack_action = attack_action.squeeze()
                    
                    # SAC Defender action
                    defend_prediction = sac_defender.predict(state, deterministic=True)
                    defend_action = defend_prediction[0] if isinstance(defend_prediction, tuple) else defend_prediction
                    if isinstance(defend_action, np.ndarray):
                        defend_action = defend_action.squeeze()
                    
                    print(f"Action shapes - DQN: {dqn_action.shape if hasattr(dqn_action, 'shape') else 'scalar'}, "
                          f"Attacker: {attack_action.shape if hasattr(attack_action, 'shape') else 'scalar'}, "
                          f"Defender: {defend_action.shape if hasattr(defend_action, 'shape') else 'scalar'}")
                    
                except Exception as e:
                    print(f"Error in action prediction: {str(e)}")
                    continue
                
                # Calculate losses
                try:
                    # Zero gradients
                    optimizer.zero_grad()
                    
                    # Ensure actions are properly shaped for physics_loss
                    attack_tensor = torch.tensor(
                        attack_action.reshape(1, -1) if hasattr(attack_action, 'reshape') else [[attack_action]], 
                        dtype=torch.float32
                    )
                    defend_tensor = torch.tensor(
                        defend_action.reshape(1, -1) if hasattr(defend_action, 'reshape') else [[defend_action]], 
                        dtype=torch.float32
                    )
                    
                    losses = physics_loss(
                        model=model,
                        t=torch.tensor([[epoch * TIME_STEP]], dtype=torch.float32),
                        Y_bus_torch=Y_bus_torch,
                        bus_data=bus_data_torch,
                        attack_actions=attack_tensor,
                        defend_actions=defend_tensor
                    )
                    
                    if not isinstance(losses, tuple) or len(losses) != 5:
                        print(f"Invalid losses returned in epoch {epoch}")
                        continue
                        
                    total_loss, pf_loss, ev_loss, wac_loss, v_loss = losses
                    
                    # Update history
                    history['total_loss'].append(float(total_loss.item()))
                    history['power_flow_loss'].append(float(pf_loss.item()))
                    history['evcs_loss'].append(float(ev_loss.item()))
                    history['wac_loss'].append(float(wac_loss.item()))
                    history['v_reg_loss'].append(float(v_loss.item()))
                    
                    # Calculate and apply gradients if loss is valid
                    if torch.isfinite(total_loss):
                        total_loss.backward()
                        optimizer.step()
                    
                except Exception as e:
                    print(f"\nDetailed Error Information for epoch {epoch}:")
                    print(f"Error Type: {type(e).__name__}")
                    print(f"Error Message: {str(e)}")
                    print("\nInput Shapes:")
                    try:
                        print(f"- Time tensor shape: {torch.tensor([[epoch * TIME_STEP]], dtype=torch.float32).shape}")
                        print(f"- Y_bus_torch shape: {Y_bus_torch.shape}")
                        print(f"- Bus data shape: {bus_data_torch.shape}")
                        print(f"- Attack actions shape: {attack_tensor.shape}")
                        print(f"- Defend actions shape: {defend_tensor.shape}")
                    except Exception as shape_error:
                        print(f"Error getting shapes: {shape_error}")
                    
                    print("\nTensor Values:")
                    try:
                        print(f"- Attack tensor: {attack_tensor[:5]}...")  # First 5 values
                        print(f"- Defend tensor: {defend_tensor[:5]}...")  # First 5 values
                    except Exception as value_error:
                        print(f"Error getting tensor values: {value_error}")
                    
                    print("\nModel State:")
                    try:
                        print(f"- Number of parameters: {sum(p.numel() for p in model.parameters())}")
                        print(f"- First layer weights shape: {next(model.parameters()).shape}")
                    except Exception as model_error:
                        print(f"Error getting model info: {model_error}")
                    
                    print("\nTraceback:")
                    import traceback
                    traceback.print_exc()
                    
                    print("\nEnvironment State:")
                    try:
                        print(f"- Current state shape: {state.shape}")
                        print(f"- DQN action: {dqn_action}")
                        print(f"- Attack action: {attack_action}")
                        print(f"- Defend action: {defend_action}")
                    except Exception as env_error:
                        print(f"Error getting environment info: {env_error}")
                        
                    continue
                    
                # Take environment step
                try:
                    next_state, rewards, done, truncated, info = env.step({
                        'dqn': dqn_action,
                        'attacker': attack_action,
                        'defender': defend_action
                    })
                    
                except Exception as e:
                    print(f"Error in environment step for epoch {epoch}: {str(e)}")
                    continue
                
            except Exception as e:
                print(f"Error in epoch {epoch}: {str(e)}")
                continue
        
        return model, history
        
    except Exception as e:
        print(f"Training error: {str(e)}")
        return initial_model, None

def evaluate_model_with_three_agents(env, dqn_agent, sac_attacker, sac_defender, num_steps=1500):
    """Evaluate the environment with DQN, SAC attacker, and SAC defender agents."""
    # Initialize tracking data with numpy arrays of known size
    tracking_data = {
        'time_steps': np.zeros(num_steps),
        'cumulative_deviations': np.zeros(num_steps),
        'voltage_deviations': np.zeros((num_steps, env.NUM_EVCS)),
        'attack_active_states': np.zeros(num_steps, dtype=bool),
        'target_evcs_history': np.zeros((num_steps, env.NUM_EVCS)),
        'attack_durations': np.zeros(num_steps),
        'dqn_actions': np.zeros(num_steps),
        'sac_attacker_actions': np.zeros((num_steps, env.NUM_EVCS * 2)),
        'sac_defender_actions': np.zeros((num_steps, env.NUM_EVCS * 2)),
        'observations': np.zeros((num_steps, env.observation_space.shape[0])),
        'rewards': np.zeros(num_steps),
        'evcs_attack_durations': {i: [] for i in range(env.NUM_EVCS)},
        'attack_counts': np.zeros(env.NUM_EVCS),
        'total_durations': np.zeros(env.NUM_EVCS)
    }

    try:
        # Reset environment
        reset_result = env.reset()
        if isinstance(reset_result, tuple):
            state, _ = reset_result
        else:
            state = reset_result

        if state is None:
            raise ValueError("Environment reset returned None state")

        valid_steps = 0  # Track number of valid steps

        for step in range(num_steps):
            try:
                # Calculate current time
                current_time = step * env.TIME_STEP
                tracking_data['time_steps'][step] = current_time

                # Get DQN action
                dqn_raw = dqn_agent.predict(state, deterministic=True)
                dqn_action = dqn_raw[0] if isinstance(dqn_raw, tuple) else dqn_raw
                if isinstance(dqn_action, np.ndarray) and dqn_action.size == 1:
                    dqn_action = int(dqn_action.item())

                # Get SAC actions
                attacker_action = sac_attacker.predict(state, deterministic=True)[0]
                defender_action = sac_defender.predict(state, deterministic=True)[0]

                # Take environment step
                next_state, rewards, done, truncated, info = env.step({
                    'dqn': dqn_action,
                    'attacker': attacker_action,
                    'defender': defender_action
                })

                # Store data
                tracking_data['cumulative_deviations'][step] = info.get('cumulative_deviation', 0.0)
                tracking_data['voltage_deviations'][step] = info.get('voltage_deviations', np.zeros(env.NUM_EVCS))
                tracking_data['attack_active_states'][step] = info.get('attack_active', False)
                tracking_data['target_evcs_history'][step] = info.get('target_evcs', np.zeros(env.NUM_EVCS))
                tracking_data['attack_durations'][step] = info.get('attack_duration', 0.0)
                tracking_data['dqn_actions'][step] = dqn_action
                tracking_data['sac_attacker_actions'][step] = attacker_action
                tracking_data['sac_defender_actions'][step] = defender_action
                tracking_data['observations'][step] = next_state
                tracking_data['rewards'][step] = float(rewards) if isinstance(rewards, (int, float)) else 0.0

                # Update EVCS-specific attack data
                target_evcs = info.get('target_evcs', np.zeros(env.NUM_EVCS))
                attack_duration = info.get('attack_duration', 0.0)
                for i in range(env.NUM_EVCS):
                    if target_evcs[i] == 1:
                        tracking_data['evcs_attack_durations'][i].append(attack_duration)
                        tracking_data['attack_counts'][i] += 1
                        tracking_data['total_durations'][i] += attack_duration

                state = next_state
                valid_steps += 1

                if done:
                    break

            except Exception as step_error:
                print(f"Error in evaluation step {step}: {step_error}")
                continue

        # Trim arrays to valid steps
        if valid_steps > 0:
            for key in tracking_data:
                if isinstance(tracking_data[key], np.ndarray):
                    tracking_data[key] = tracking_data[key][:valid_steps]

        # Calculate average attack durations
        avg_attack_durations = np.zeros(env.NUM_EVCS)
        for i in range(env.NUM_EVCS):
            if tracking_data['attack_counts'][i] > 0:
                avg_attack_durations[i] = tracking_data['total_durations'][i] / tracking_data['attack_counts'][i]
        tracking_data['avg_attack_durations'] = avg_attack_durations

        return tracking_data

    except Exception as e:
        print(f"Error in evaluation: {str(e)}")
        # Return minimal valid data structure
        return {
            'time_steps': np.array([0.0]),
            'cumulative_deviations': np.array([0.0]),
            'voltage_deviations': np.zeros((1, env.NUM_EVCS)),
            'attack_active_states': np.array([False]),
            'target_evcs_history': np.zeros((1, env.NUM_EVCS)),
            'attack_durations': np.array([0.0]),
            'dqn_actions': np.array([0]),
            'sac_attacker_actions': np.zeros((1, env.NUM_EVCS * 2)),
            'sac_defender_actions': np.zeros((1, env.NUM_EVCS * 2)),
            'observations': np.zeros((1, env.observation_space.shape[0])),
            'rewards': np.array([0.0]),
            'avg_attack_durations': np.zeros(env.NUM_EVCS)
        }

def check_constraints(state, info):
    """Helper function to check individual constraints."""
    violations = []
    
    # Convert state to tensor if it's not already
    if not torch.is_tensor(state):
        state = torch.tensor(state)
    
    # Extract relevant state components
    voltage_indices = slice(0, NUM_BUSES)
    current_indices = slice(NUM_BUSES, 2*NUM_BUSES)
    
    # Check voltage constraints (0.9 to 1.1 p.u.)
    voltages = state[voltage_indices]
    if torch.any(voltages < 0.8) or torch.any(voltages > 1.2):
        violations.append({
            'type': 'Voltage',
            'values': voltages.cpu().numpy(),
            'limits': (0.8, 1.2),
            'violated_indices': torch.where((voltages < 0.8) | (voltages > 1.2))[0].cpu().numpy()
        })

    # Check current constraints (-1.0 to 1.0 p.u.)
    currents = state[current_indices]
    if torch.any(torch.abs(currents) > 1.0):
        violations.append({
            'type': 'Current',
            'values': currents.cpu().numpy(),
            'limits': (-1.0, 1.0),
            'violated_indices': torch.where(torch.abs(currents) > 1.0)[0].cpu().numpy()
        })

    # Check power constraints if available in state
    if 'power_output' in info:
        power = torch.tensor(info['power_output'])
        if torch.any(torch.abs(power) > 1.0):
            violations.append({
                'type': 'Power',
                'values': power.cpu().numpy(),
                'limits': (-1.0, 1.0),
                'violated_indices': torch.where(torch.abs(power) > 1.0)[0].cpu().numpy()
            })

    # Check SOC constraints if available
    if 'soc' in info:
        soc = torch.tensor(info['soc'])
        if torch.any((soc < 0.1) | (soc > 0.9)):
            violations.append({
                'type': 'State of Charge',
                'values': soc.cpu().numpy(),
                'limits': (0.1, 0.9),
                'violated_indices': torch.where((soc < 0.1) | (soc > 0.9))[0].cpu().numpy()
            })

    return violations, info

def validate_physics_constraints(env, dqn_agent, sac_attacker, sac_defender, num_episodes=5):
    """Validate that the agents respect physics constraints with detailed reporting."""
    for episode in range(num_episodes):
        state, _ = env.reset()
        done = False
        step_count = 0
        
        while not done and step_count < 100:
            try:
                # Get actions from all agents
                dqn_action_scalar = dqn_agent.predict(state, deterministic=True)[0]
                dqn_action = env.decode_dqn_action(dqn_action_scalar)
                attacker_action = sac_attacker.predict(state, deterministic=True)[0]
                defender_action = sac_defender.predict(state, deterministic=True)[0]
                
                # Combine actions
                action = {
                    'dqn': dqn_action,
                    'attacker': attacker_action,
                    'defender': defender_action
                }
                
                # Take step in environment
                next_state, rewards, done, truncated, info = env.step(action)
                
                # Convert state to tensor for constraint checking
                if not torch.is_tensor(next_state):
                    next_state_tensor = torch.tensor(next_state, dtype=torch.float32)
                else:
                    next_state_tensor = next_state
                
                # Check for physics violations
                violations = check_constraints(next_state_tensor, info)
                
                if violations:
                    print(f"\nPhysics constraints violated in episode {episode}, step {step_count}:")
                    for violation in violations:
                        print(f"\nViolation Type: {violation['type']}")
                        print(f"Limits: {violation['limits']}")
                    return False
                
                state = next_state
                step_count += 1
                
            except Exception as e:
                print(f"Error in validation step: {e}")
                return False
            
    print("All physics constraints validated successfully!")
    return True, info

def plot_evaluation_results(results, save_dir="./figures"):
    """Plot evaluation results with PyTorch tensor handling."""
    # Create directory if it doesn't exist
    os.makedirs(save_dir, exist_ok=True)
    
    # Generate timestamp for unique filenames
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    # Convert tensors to numpy arrays if needed
    def to_numpy(data):
        if torch.is_tensor(data):
            return data.cpu().numpy()
        elif isinstance(data, np.ndarray):
            return data
        else:
            return np.array(data)
    
    # Extract and convert data
    time_steps = to_numpy(results['time_steps'])
    cumulative_deviations = to_numpy(results['cumulative_deviations'])
    voltage_deviations = to_numpy(results['voltage_deviations'])
    attack_active_states = to_numpy(results['attack_active_states'])
    avg_attack_durations = to_numpy(results['avg_attack_durations'])

    # Plot cumulative deviations over time
    plt.figure(figsize=(12, 6))
    plt.plot(time_steps, cumulative_deviations, label='Cumulative Deviations')
    plt.xlabel('Time (s)')
    plt.ylabel('Cumulative Deviations')
    plt.title('Cumulative Deviations Over Time')
    plt.legend()
    plt.grid(True)
    plt.savefig(f"{save_dir}/cumulative_deviations_{timestamp}.png", dpi=300, bbox_inches='tight')
    plt.close()

    # Plot total rewards over time
    plt.figure(figsize=(12, 6))
    total_rewards = []
    for reward in results['rewards']:
        if isinstance(reward, dict):
            total_rewards.append(reward.get('attacker', 0) + reward.get('defender', 0))
        elif torch.is_tensor(reward):
            total_rewards.append(float(reward.item()))
        else:
            total_rewards.append(float(reward))
    
    plt.plot(time_steps, total_rewards, label='Total Rewards')
    plt.xlabel('Time (s)')
    plt.ylabel('Total Rewards')
    plt.title('Total Rewards Over Time')
    plt.legend()
    plt.grid(True)
    plt.savefig(f"{save_dir}/rewards_{timestamp}.png", dpi=300, bbox_inches='tight')
    plt.close()

    # Additional plots...
    # (Rest of the plotting code remains the same, just ensure data is converted using to_numpy)


    # Plot voltage deviations for each EVCS over time
    plt.figure(figsize=(12, 6))
    for i in range(voltage_deviations.shape[1]):
        plt.plot(time_steps, voltage_deviations[:, i], label=f'EVCS {i+1} Voltage Deviation')
    plt.xlabel('Time (s)')
    plt.ylabel('Voltage Deviation (p.u.)')
    plt.title('Voltage Deviations Over Time')
    plt.legend()
    plt.grid(True)
    plt.savefig(f"{save_dir}/voltage_deviations_{timestamp}.png", dpi=300, bbox_inches='tight')
    plt.close()

    # Plot attack active states over time
    plt.figure(figsize=(12, 6))
    plt.plot(time_steps, attack_active_states, label='Attack Active State')
    plt.xlabel('Time (s)')
    plt.ylabel('Attack Active State')
    plt.title('Attack Active State Over Time')
    plt.legend()
    plt.grid(True)
    plt.savefig(f"{save_dir}/attack_states_{timestamp}.png", dpi=300, bbox_inches='tight')
    plt.close()

    # Plot average attack durations for each EVCS
    plt.figure(figsize=(12, 6))
    plt.bar(range(len(avg_attack_durations)), avg_attack_durations, tick_label=[f'EVCS {i+1}' for i in range(len(avg_attack_durations))])
    plt.xlabel('EVCS')
    plt.ylabel('Average Attack Duration (s)')
    plt.title('Average Attack Duration for Each EVCS')
    plt.grid(True)
    plt.savefig(f"{save_dir}/avg_attack_durations_{timestamp}.png", dpi=300, bbox_inches='tight')
    plt.close()

def plot_training_history(history):
    """Plot training history metrics."""
    plt.figure(figsize=(15, 10))
    
    # Plot all losses
    for key, values in history.items():
        plt.plot(values, label=key)
    
    plt.xlabel('Epoch')
    plt.ylabel('Loss')
    plt.title('Training History')
    plt.legend()
    plt.grid(True)
    plt.yscale('log')  # Use log scale for better visualization
    
    # Save the plot
    plt.savefig('./figures/training_history.png', dpi=300, bbox_inches='tight')
    plt.close()

def prepare_results_for_plotting(results):
    """Convert results dictionary or tuple to plotting-friendly format."""
    # Handle tuple case
    if isinstance(results, tuple):
        # If it's a tuple with two elements (results, info), take the first element
        results = results[0] if len(results) > 0 else {}
    
    # Handle None case
    if results is None:
        return {}
        
    # Now process as dictionary
    prepared_results = {}
    if isinstance(results, dict):
        for key, value in results.items():
            if isinstance(value, torch.Tensor):
                prepared_results[key] = value.detach().cpu().numpy()
            elif isinstance(value, dict):
                prepared_results[key] = value  # Keep dictionaries as-is
            else:
                prepared_results[key] = value
    
    return prepared_results

if __name__ == '__main__':
    # Set device
    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    
    # Define physics parameters
    physics_params = {
        'voltage_limits': (torch.tensor(0.8, device=device), torch.tensor(1.2, device=device)),
        'v_out_nominal': torch.tensor(1.0, device=device),
        'current_limits': (torch.tensor(-1.0, device=device), torch.tensor(1.0, device=device)),
        'i_rated': torch.tensor(1.0, device=device),
        'attack_magnitude': torch.tensor(0.01, device=device),
        'current_magnitude': torch.tensor(0.03, device=device),
        'wac_kp_limits': (torch.tensor(0.0, device=device), torch.tensor(2.0, device=device)),
        'wac_ki_limits': (torch.tensor(0.0, device=device), torch.tensor(2.0, device=device)),
        'control_saturation': torch.tensor(0.3, device=device),
        'power_limits': (torch.tensor(-1.0, device=device), torch.tensor(1.0, device=device)),
        'power_ramp_rate': torch.tensor(0.1, device=device),
        'evcs_efficiency': torch.tensor(0.98, device=device),
        'soc_limits': (torch.tensor(0.1, device=device), torch.tensor(0.9, device=device))
    }

    # Initialize the PINN model
    initial_pinn_model = EVCS_PowerSystem_PINN().to(device)

    # Setup logging directories
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_dir = f"./logs/{timestamp}"
    model_dir = f"./models/{timestamp}"
    for dir_path in [log_dir, model_dir]:
        os.makedirs(dir_path, exist_ok=True)

    # Create the Discrete Environment
    print("Creating the DiscreteHybridEnv environment...")
    discrete_env = DiscreteHybridEnv(
        pinn_model=initial_pinn_model,
        y_bus_torch=Y_bus_torch.to(device),
        bus_data=bus_data,
        v_base_lv=torch.tensor(V_BASE_DC, device=device),
        num_evcs=NUM_EVCS,
        num_buses=NUM_BUSES,
        time_step=TIME_STEP,
        **physics_params
    )

    # Initialize callbacks
    dqn_checkpoint = CheckpointCallback(
        save_freq=1000,
        save_path=f"{model_dir}/dqn_checkpoints/",
        name_prefix="dqn"
    )
    
    # Initialize the DQN Agent
    print("Initializing the DQN agent...")
    dqn_agent = DQN(
        'MlpPolicy',
        discrete_env,
        verbose=1,
        learning_rate=3e-3,
        buffer_size=10000,
        exploration_fraction=0.3,
        exploration_final_eps=0.2,
        train_freq=4,
        batch_size=32,
        gamma=0.99,
        device=device,
        tensorboard_log=f"{log_dir}/dqn/"
    )

    # Train DQN
    print("Training DQN agent...")
    dqn_agent.learn(
        total_timesteps=500,
        callback=dqn_checkpoint,
        progress_bar=True
    )
    dqn_agent.save(f"{model_dir}/dqn_final")

    # Create environments
    print("Creating environments...")
    combined_env = CompetingHybridEnv(
        pinn_model=initial_pinn_model,
        y_bus_torch=Y_bus_torch.to(device),
        bus_data=bus_data,
        v_base_lv=torch.tensor(V_BASE_DC, device=device),
        dqn_agent=dqn_agent,
        num_evcs=NUM_EVCS,
        num_buses=NUM_BUSES,
        time_step=TIME_STEP,
        **physics_params
    )

    # Create SAC environments and agents
    print("Creating SAC agents...")
    sac_attacker_env = SACWrapper(env=combined_env, agent_type='attacker', dqn_agent=dqn_agent)
    sac_defender_env = SACWrapper(env=combined_env, agent_type='defender', dqn_agent=dqn_agent)

    sac_attacker = SAC(
        'MlpPolicy',
        sac_attacker_env,
        verbose=1,
        learning_rate=5e-4,
        buffer_size=10000,
        batch_size=128,
        gamma=0.99,
        tau=0.005,
        ent_coef='auto',
        device=device,
        tensorboard_log=f"{log_dir}/sac_attacker/"
    )

    sac_defender = SAC(
        'MlpPolicy',
        sac_defender_env,
        verbose=1,
        learning_rate=1e-6,
        buffer_size=3000,
        batch_size=64,
        gamma=0.99,
        tau=0.005,
        ent_coef='auto',
        device=device,
        tensorboard_log=f"{log_dir}/sac_defender/"
    )

    # Update wrapper environments
    sac_attacker_env.sac_defender = sac_defender
    sac_defender_env.sac_attacker = sac_attacker

    # Create callbacks
    sac_callbacks = {
        'attacker': CheckpointCallback(
            save_freq=1000,
            save_path=f"{model_dir}/sac_attacker_checkpoints/",
            name_prefix="attacker"
        ),
        'defender': CheckpointCallback(
            save_freq=1000,
            save_path=f"{model_dir}/sac_defender_checkpoints/",
            name_prefix="defender"
        )
    }


    sac_attacker.learn(
        total_timesteps=500,
        callback=sac_callbacks['attacker'],
        progress_bar=True
    )

    sac_attacker.save(f"{model_dir}/sac_attacker_final")

    sac_defender.learn(
        total_timesteps=500,
        callback=sac_callbacks['defender'],
        progress_bar=True
    )

    sac_defender.save(f"{model_dir}/sac_defender_final")

    # Joint training loop
    num_iterations = 1
    print("Starting joint training...")
    for iteration in range(num_iterations):
        print(f"\nJoint training iteration {iteration + 1}/{num_iterations}")
        
        for agent, name, callback, env in [
            (dqn_agent, "DQN", dqn_checkpoint, discrete_env),
            (sac_attacker, "SAC Attacker", sac_callbacks['attacker'], sac_attacker_env),
            (sac_defender, "SAC Defender", sac_callbacks['defender'], sac_defender_env)
        ]:
            print(f"\nTraining {name}...")
            total_timesteps = 250 if name == "SAC Defender" else 500
            agent.learn(
                total_timesteps=total_timesteps,
                callback=callback,
                progress_bar=True
            )
            agent.save(f"{model_dir}/{name.lower()}_iter_{iteration + 1}")

            # Update environment references
            combined_env.update_agents(dqn_agent, sac_attacker, sac_defender)
            sac_attacker_env.update_agents(sac_defender=sac_defender, dqn_agent=dqn_agent)
            sac_defender_env.update_agents(sac_attacker=sac_attacker, dqn_agent=dqn_agent)

    # Train PINN model
    print("\nTraining PINN model...")
    trained_pinn_model, training_history = train_model(
        initial_model=initial_pinn_model,
        dqn_agent=dqn_agent,
        sac_attacker=sac_attacker,
        sac_defender=sac_defender,
        Y_bus_torch=Y_bus_torch,
        bus_data=bus_data,
        epochs=50,
        batch_size=128
    )

    # Plot training history
    if training_history is not None:
        plot_training_history(training_history)

    print("Creating a new CompetingHybridEnv environment with the trained PINN model...")
    trained_combined_env = CompetingHybridEnv(
        pinn_model=trained_pinn_model,  # Use the trained PINN model here
        y_bus_torch=Y_bus_torch,
        bus_data=bus_data,
        v_base_lv=V_BASE_DC,
        dqn_agent=dqn_agent,  # Use the trained agents
        sac_attacker=sac_attacker,
        sac_defender=sac_defender,
        num_evcs=NUM_EVCS,
        num_buses=NUM_BUSES,
        time_step=TIME_STEP,
        **physics_params
    )

           # Update the environment's agent references if necessary
    trained_combined_env.sac_attacker = sac_attacker
    trained_combined_env.sac_defender = sac_defender
    trained_combined_env.dqn_agent = dqn_agent


    # Final evaluation
    print("\nRunning final evaluation...")
    evaluation_results = evaluate_model_with_three_agents(
        env=trained_combined_env,
        dqn_agent=dqn_agent,
        sac_attacker=sac_attacker,
        sac_defender=sac_defender,
        num_steps=100
    )

    # Prepare results for plotting with the updated function
    serializable_results = prepare_results_for_plotting(evaluation_results)

    # Only plot if we have valid results
    if serializable_results:
        plot_evaluation_results(serializable_results)
    else:
        print("Warning: No valid results to plot")

    print("\nTraining completed successfully!")