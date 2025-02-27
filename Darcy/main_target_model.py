"""
Author: Varun Kumar
Date: Jan 3 2025
Purpose: main script for training source model for Darcy flow problem
Contact: varun_kumar2@brown.edu
"""

import numpy as np
from model import DeepONet
from preprocessor import DataSet
from savedata import save_data
import os
from time import perf_counter
from loss import *
from plotting import PlotLoss
import json, yaml


def main():
    @tf.function(jit_compile=True)
    def train_step(br_input, trunk_in, target, mask):
        """
        Training step
        :param br_input: Mask + init condition input to branch network (bs,N,N,2)
        :param trunk_in: Domain points for trunk network (1,N*N,2)
        :param target: output labels (bs,N)
        :param mask: Binary Mask for geometry (bs,N)
        :return: Losses
        """

        with tf.GradientTape(persistent=False) as tape:
            br1_out, trk_out, *_ = model_target.call_don_target(
                br_input, trunk_in,
                training=True)

            br_output = br1_out
            u1_pred_train = tf.einsum("ijk,mlk->il", br_output, trk_out) * mask

            mse_loss = loss_norm(u1_pred_train, target)

            batch_loss = mse_loss + sum(model_target.losses)

        gradient_wt = tape.gradient(
            batch_loss, model_target.trainable_variables
        )

        optimizer.apply_gradients(
            zip(gradient_wt, model_target.trainable_variables)
        )

        del tape

        return (mse_loss,
                batch_loss
                )

    @tf.function(jit_compile=True)
    def eval_step(br_input, trunk_in, target, mask):
        """
        Evaluation step
        :param br_input: Mask + init condition input to branch network (bs,N,N,2)
        :param trunk_in: Domain points for trunk network (1,N*N,2)
        :param target: output labels (bs,N)
        :param mask: Binary Mask for geometry (bs,N)
        :return: errors (.), output predictions (bs,N), output ground truths (bs,N)
        """
        br1_out, trk_pred, *_ = model_target.call_don_target(br_input, trunk_in, training=False)

        br_output = br1_out
        u1_pred = tf.einsum("ijk,mlk->il", br_output, trk_pred) * mask
        u1_pred_reg, u1_target_reg = u1_pred / 10, target / 10
        batch_error1 = error_rel(u1_pred_reg, u1_target_reg)

        return (
            batch_error1,
            u1_pred_reg,
            u1_target_reg
        )

    tf_datatype = tf.float32

    """
    Loading network setup details
    """
    stream = open("network_setup_target.yaml", "r")
    setup_dict = yaml.safe_load(stream)
    trk_nodes = setup_dict["Architecture"]["Trunk_lyr"]
    cnn_mlp_nodes = setup_dict["Architecture"]["Br_mlp_lyr"]
    cnn_filtr = setup_dict["Architecture"]["Br_cnn_filters"]
    dropout_br = setup_dict["Architecture"]["Dropout_br_mlp"]
    latent_dim = setup_dict["Architecture"]["latent_dim"]
    cnn_ker_sz = setup_dict["Architecture"]["Br_cnn_ker_sz"]
    cnn_ker_stride = setup_dict["Architecture"]["Br_cnn_stride"]
    cnn_avgpool_sz = setup_dict["Architecture"]["Br_avgpool_sz"]
    br_reg_rate = setup_dict["Architecture"]["Br_regularizer"]
    br_reg_rate_trnf = setup_dict["Architecture"]["Br_regularizer_trnf"]
    trk_reg_rate = setup_dict["Architecture"]["Trk_regularizer"]
    br_cnn_act = setup_dict["Architecture"]["Br_cnn_activation"]
    br_mlp_act = setup_dict["Architecture"]["Br_mlp_activation"]
    trk_mlp_act = setup_dict["Architecture"]["Trk_mlp_activation"]
    exp_name = setup_dict["Exp_setup"]["exp_name"]
    batch_sz = setup_dict["Exp_setup"]["batch_sz"]
    num_training = setup_dict["Exp_setup"]["num_train"]
    num_testing = setup_dict["Exp_setup"]['num_test']
    src_chckpt_path = setup_dict["Exp_setup"]['src_chckpt']
    epochs = setup_dict["Exp_setup"]["epochs"]
    epoch_bounds = setup_dict["Exp_setup"]["epoch_bounds"]
    lr_values = setup_dict["Exp_setup"]["lear_rate"]
    lr_reswt = setup_dict["Exp_setup"]["lr_resadp"]
    lambda_reswt = setup_dict["Exp_setup"]["lambda_resadp"]
    source_geom = setup_dict["Exp_setup"]["source_geom"]
    target_geom = setup_dict["Exp_setup"]["target_geom"]

    """
    Setting up result directories
    """
    current_directory = os.getcwd()
    case = f"multitask_target_{exp_name}"
    results_dir = "./" + case + "/Results"
    plots_dir = "./" + case + "/plots"
    save_results_to = results_dir
    save_plots_to = plots_dir

    os.makedirs(save_results_to, mode=0o755, exist_ok=True)
    os.makedirs(save_plots_to, mode=0o755, exist_ok=True)

    data = DataSet(batch_sz)
    f_train, u_train, f_test, u_test, mask_train, mask_test, dom = data.load_data_target(num_training,
                                                                                         num_testing,
                                                                                         tf_datatype)

    model_target = DeepONet(mlp_nodes_br=cnn_mlp_nodes, act_br_cnn=br_cnn_act, act_br_mlp=br_mlp_act,
                            reg_br=br_reg_rate, reg_br_trnf=br_reg_rate_trnf, cnn_krnl_sz=cnn_ker_sz,
                            cnn_filtr=cnn_filtr, cnn_stride=cnn_ker_stride, avg_pool=cnn_avgpool_sz,
                            drpout_rate_br=dropout_br, trk_nodes=trk_nodes, act_trk=trk_mlp_act, reg_trk=trk_reg_rate,
                            latent_dim=latent_dim)

    """
    Initializing with source model weights and setting required layers to be trainable
    """
    model_target.load_weights(src_chckpt_path)

    for i, l in enumerate(model_target.layers):
        lyr_name = str(l.name)
        if lyr_name == 'mlp1':
            model_target.layers[i].trainable = True
        elif lyr_name == 'mlp2':
            model_target.layers[i].trainable = True
        elif lyr_name == 'mlp3':
            model_target.layers[i].trainable = True
        elif lyr_name == 'cnn_l1':
            model_target.layers[i].trainable = True
        elif lyr_name == 'trk_out':
            model_target.layers[i].trainable = True
        # elif lyr_name == 'trk_l4':
        #     model_target.layers[i].trainable = True       # Set to True to enable additional trunk layer for training
        else:
            model_target.layers[i].trainable = False

    """
    Setting up data loader and randomizer
    """
    train_dataset = tf.data.Dataset.from_tensor_slices(
        (f_train, u_train, mask_train))  #
    train_dataset = train_dataset.shuffle(buffer_size=num_training).batch(batch_sz)

    """
    Training setup
    """
    lr_schedule = tf.keras.optimizers.schedules.PiecewiseConstantDecay(
        epoch_bounds, lr_values
    )
    optimizer = tf.keras.optimizers.Adam(lr_schedule, beta_1=0.9, beta_2=0.99)
    batch_losstot_arr = []
    batch_lossmse_arr = []
    batch_err_arr = []
    epoch_err_arr = []
    epoch_lossmse_arr = []
    checkpoints_path = f"./checkpts/multitask_target_{exp_name}.ckpt"

    start_time = perf_counter()

    print(
        f"Starting training for Darcy transfer learning target geometry {exp_name}"
    )
    for epoch in range(epochs):
        batch_mseloss_sum = 0
        batch_err_sum = 0
        for step, (x1_batch_train, target_batch_train, mask_batch_train) in enumerate(
                train_dataset):
            """
            Training and validation steps
            """
            mse_loss, total_loss = train_step(x1_batch_train, dom, target_batch_train,
                                              mask_batch_train)
            batch_lossmse_arr.append(mse_loss.numpy())
            batch_losstot_arr.append(total_loss.numpy())

            l2_err, *_ = eval_step(f_test, dom, u_test, mask_test)
            batch_err_arr.append(l2_err.numpy())

            batch_mseloss_sum += mse_loss.numpy()
            batch_err_sum += l2_err.numpy()

            print('\r',
                  f' Step --> {step}, Batch mse loss --> {mse_loss.numpy()}, Batch error --> {l2_err.numpy()}',
                  end='')

        epoch_lossmse_arr.append(batch_mseloss_sum)
        epoch_err_arr.append(batch_err_sum)

        if epoch % 20 == 0:
            time_step_100 = perf_counter()
            comp_time = time_step_100 - start_time
            print(
                "\n",
                f"Epoch {epoch}, Total mse loss --> {batch_mseloss_sum}, validation error -->{batch_err_sum}, Computation time --> {comp_time}")
            print("*" * 100)
            start_time = perf_counter()

    print('\n' 'Training completed')
    model_target.save_weights(checkpoints_path, overwrite=True)

    loss_plot = PlotLoss(save_results_to + f'/loss_target_{exp_name}.png')
    loss_plot.plot_loss_target(batch_lossmse_arr, batch_err_arr)
    print('\n' 'Loss plot saved')

    with open(current_directory + '/' + case + "/setup.json", "w") as outfile:
        json.dump(setup_dict, outfile)

    print('\n' 'Saved JSON and keras model')

    model_target.load_weights(checkpoints_path)
    l2_err, pred, target = eval_step(f_test, dom, u_test, mask_test)
    mask_test_arr = tf.where(tf.equal(mask_test, 0), -1., mask_test)

    np.savez_compressed(save_results_to + f'/multitask_target_{exp_name}.npz', model_out=pred.numpy(),
                        gt=target.numpy(),
                        l2_error=l2_err.numpy(), dom=tf.reshape(dom, [dom.shape[1], dom.shape[2]]).numpy(),
                        epoch_loss=epoch_lossmse_arr, epoch_err=epoch_err_arr, batch_loss=batch_lossmse_arr,
                        batch_err=batch_err_arr, plot_mask=mask_test_arr.numpy())

    save_data(f_test, pred.numpy(), target.numpy(), save_results_to, 'target', f'{exp_name}')
    print('\n' 'Data saved successfully')

    pass


if __name__ == "__main__":
    main()
