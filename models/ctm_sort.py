import torch
import numpy as np
from models.ctm import ContinuousThoughtMachine, NeuronSelectType

class ContinuousThoughtMachineSORT(ContinuousThoughtMachine):
    """
    Slight adaption of the CTM to work with the sort task.
    """                               

    def __init__(self,
                 iterations: int,
                 d_model: int,
                 d_input: int,
                 heads: int,
                 n_synch_out: int,
                 n_synch_action: int,
                 synapse_depth: int,
                 memory_length: int,
                 deep_nlms: bool,
                 memory_hidden_dims: int,
                 do_layernorm_nlm: bool,
                 backbone_type: str,
                 positional_embedding_type: str,
                 out_dims: int,
                 prediction_reshaper: list[int] = [-1],
                 dropout: float = 0,
                 dropout_nlm: float | None = None,
                 neuron_select_type: NeuronSelectType = 'random-pairing',  
                 n_random_pairing_self: int = 0,
                 ):
        super().__init__(
            iterations=iterations,
            d_model=d_model,
            d_input=d_input,
            heads=0,
            n_synch_out=n_synch_out,
            n_synch_action=0,
            synapse_depth=synapse_depth,
            memory_length=memory_length,
            deep_nlms=deep_nlms,
            memory_hidden_dims=memory_hidden_dims,
            do_layernorm_nlm=do_layernorm_nlm,
            backbone_type='none',
            positional_embedding_type='none',
            out_dims=out_dims,
            prediction_reshaper=prediction_reshaper,
            dropout=dropout,
            dropout_nlm=dropout_nlm,
            neuron_select_type=neuron_select_type,
            n_random_pairing_self=n_random_pairing_self,
        )

        # --- Use a minimal CTM w/out input (action) synch ---
        self.neuron_select_type_action = None
        self.synch_representation_size_action = None

        self.attention = None  # Should already be None because super(... heads=0... ) 
        self.q_proj = None  # Should already be None because super(... heads=0... ) 
        self.kv_proj = None  # Should already be None because super(... heads=0... ) 




    def forward(self, x: torch.Tensor, track: bool = False):
        B = x.size(0)
        device = x.device

        # --- Tracking Initialization ---
        pre_activations_tracking = []
        post_activations_tracking = []
        synch_out_tracking = []
        attention_tracking = []

        # --- For SORT: no need to featurise data ---
        

        # --- Initialise Recurrent State ---
        state_trace = self.start_trace.unsqueeze(0).expand(B, -1, -1) # Shape: (B, H, T)
        activated_state = self.start_activated_state.unsqueeze(0).expand(B, -1) # Shape: (B, H)

        # --- Prepare Storage for Outputs per Iteration ---
        predictions = torch.empty(B, self.out_dims, self.iterations, device=device, dtype=x.dtype)
        certainties = torch.empty(B, 2, self.iterations, device=device, dtype=x.dtype)

        # --- Initialise Recurrent Synch Values  ---
        r_out = torch.exp(-torch.clamp(self.decay_params_out, 0, 15)).unsqueeze(0).repeat(B, 1)
        _, decay_alpha_out, decay_beta_out = self.compute_synchronisation(activated_state, None, None, r_out, synch_type='out')
        # Compute learned weighting for synchronisation
        

        # --- Recurrent Loop  ---
        for stepi in range(self.iterations):

            pre_synapse_input = torch.concatenate((x, activated_state), dim=-1)

            # --- Apply Synapses ---
            state = self.synapses(pre_synapse_input)
            # The 'state_trace' is the history of incoming pre-activations
            state_trace = torch.cat((state_trace[:, :, 1:], state.unsqueeze(-1)), dim=-1)

            # --- Apply Neuron-Level Models ---
            activated_state = self.trace_processor(state_trace)
            # One would also keep an 'activated_state_trace' as the history of outgoing post-activations
            # BUT, this is unnecessary because the synchronisation calculation is fully linear and can be
            # done using only the currect activated state (see compute_synchronisation method for explanation)

            # --- Calculate Synchronisation for Output Predictions ---
            synchronisation_out, decay_alpha_out, decay_beta_out = self.compute_synchronisation(activated_state, decay_alpha_out, decay_beta_out, r_out, synch_type='out')

            # --- Get Predictions and Certainties ---
            current_prediction = self.output_projector(synchronisation_out)
            current_certainty = self.compute_certainty(current_prediction)

            predictions[..., stepi] = current_prediction
            certainties[..., stepi] = current_certainty

            # --- Tracking ---
            if track:
                pre_activations_tracking.append(state_trace[:,:,-1].detach().cpu().numpy())
                post_activations_tracking.append(activated_state.detach().cpu().numpy())
                synch_out_tracking.append(synchronisation_out.detach().cpu().numpy())

        # --- Return Values ---
        if track:
            return predictions, certainties, np.array(synch_out_tracking), np.array(pre_activations_tracking), np.array(post_activations_tracking), np.array(attention_tracking)
        return predictions, certainties, synchronisation_out
