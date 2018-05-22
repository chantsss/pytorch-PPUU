import torch, numpy, argparse, pdb, os, time, math
import utils
from dataloader import DataLoader
from torch.autograd import Variable
import torch.nn.functional as F
import torch.optim as optim

import importlib

import models2 as models

#################################################
# Train an action-conditional forward model
#################################################

parser = argparse.ArgumentParser()
# data params
parser.add_argument('-dataset', type=str, default='i80')
parser.add_argument('-model', type=str, default='fwd-cnn')
parser.add_argument('-decoder', type=int, default=0)
parser.add_argument('-loss2', type=str, default='pdf')
parser.add_argument('-nshards', type=int, default=20)
parser.add_argument('-data_dir', type=str, default='/misc/vlgscratch4/LecunGroup/nvidia-collab/data/')
parser.add_argument('-model_dir', type=str, default='/misc/vlgscratch4/LecunGroup/nvidia-collab/')
parser.add_argument('-n_episodes', type=int, default=20)
parser.add_argument('-lanes', type=int, default=8)
parser.add_argument('-ncond', type=int, default=10)
parser.add_argument('-npred', type=int, default=20)
parser.add_argument('-seed', type=int, default=1)
parser.add_argument('-batch_size', type=int, default=16)
parser.add_argument('-nfeature', type=int, default=96)
parser.add_argument('-n_hidden', type=int, default=100)
parser.add_argument('-tie_action', type=int, default=0)
parser.add_argument('-beta', type=float, default=1.0)
parser.add_argument('-nz', type=int, default=2)
parser.add_argument('-lrt', type=float, default=0.0001)
parser.add_argument('-epoch_size', type=int, default=4000)
parser.add_argument('-zeroact', type=int, default=0)
parser.add_argument('-warmstart', type=int, default=0)
parser.add_argument('-z_sphere', type=int, default=0)
parser.add_argument('-combine', type=str, default='mult')
parser.add_argument('-n_mixture', type=int, default=10)
parser.add_argument('-debug', type=int, default=0)
opt = parser.parse_args()

opt.model_dir += f'/dataset_{opt.dataset}_costs2/models2/'
if opt.dataset == 'simulator':
    opt.model_dir += f'_{opt.nshards}-shards/'
    data_file = f'{opt.data_dir}/traffic_data_lanes={opt.lanes}-episodes=*-seed=*.pkl'
else:
    data_file = None
os.system('mkdir -p ' + opt.model_dir)


dataloader = DataLoader(data_file, opt, opt.dataset)

opt.model_file = f'{opt.model_dir}/model={opt.model}-bsize={opt.batch_size}-ncond={opt.ncond}-npred={opt.npred}-lrt={opt.lrt}-nhidden={opt.n_hidden}-nfeature={opt.nfeature}-decoder={opt.decoder}-combine={opt.combine}'

if opt.zeroact == 1:
    opt.model_file += '-zeroact'

if 'vae' or 'fwd-cnn-ae' in opt.model:
    opt.model_file += f'-nz={opt.nz}'
    opt.model_file += f'-beta={opt.beta}'

if 'fwd-cnn-ae' in opt.model:
    opt.model_file += f'-nmix={opt.n_mixture}'

if '-ae-lp' in opt.model:
    opt.model_file += f'-loss_p={opt.loss2}'



opt.model_file += f'-warmstart={opt.warmstart}'
print(f'[will save model as: {opt.model_file}]')

opt.n_inputs = 4
opt.n_actions = 2
if opt.dataset == 'simulator':
    opt.height = 97
    opt.width = 20
    opt.h_height = 12
    opt.h_width = 2

elif opt.dataset == 'i80':
    opt.height = 117
    opt.width = 24
    opt.h_height = 14
    opt.h_width = 3
    opt.hidden_size = opt.nfeature*opt.h_height*opt.h_width

if opt.warmstart == 1:
    prev_model = f'/misc/vlgscratch4/LecunGroup/nvidia-collab/dataset_{opt.dataset}_costs2/models/'
    prev_model += f'model=fwd-cnn-bsize=16-ncond={opt.ncond}-npred={opt.npred}-lrt=0.0002-nhidden=100-nfeature={opt.nfeature}-decoder={opt.decoder}-combine={opt.combine}-warmstart=0.model'
else:
    prev_model = ''

if opt.model == 'fwd-cnn-vae-fp':
    model = models.FwdCNN_VAE_FP(opt, mfile=prev_model)
elif opt.model == 'fwd-cnn-vae-lp':
    model = models.FwdCNN_VAE_LP(opt, mfile=prev_model)
elif opt.model == 'fwd-cnn-een-lp':
    model = models.FwdCNN_EEN_LP(opt, mfile=prev_model)
elif opt.model == 'fwd-cnn-een-fp':
    model = models.FwdCNN_EEN_FP(opt, mfile=prev_model)
elif opt.model == 'fwd-cnn-ae-fp':
    model = models.FwdCNN_AE_FP(opt, mfile=prev_model)
elif opt.model == 'fwd-cnn-ae-lp':
    model = models.FwdCNN_AE_LP(opt, mfile=prev_model)
elif opt.model == 'fwd-cnn':
    model = models.FwdCNN(opt, mfile=prev_model)
elif opt.model == 'fwd-cnn-mdn':
    model = models.FwdCNN_MDN(opt, mfile='')
elif opt.model == 'fwd-cnn2':
    model = models.FwdCNN2(opt)

model.intype('gpu')

optimizer = optim.Adam(model.parameters(), opt.lrt)


def compute_loss(targets, predictions, r=True):
    target_images, target_states, target_costs = targets
    if opt.model == 'fwd-cnn-mdn':
        pred_images, pred_states, pred_costs, latent_probs = predictions
        pred_images_mu = pred_images[0].view(opt.batch_size*opt.npred, opt.n_mixture, -1)
        pred_images_sigma = pred_images[1].view(opt.batch_size*opt.npred, opt.n_mixture, -1)
        target_images = target_images.view(opt.batch_size*opt.npred, -1)
        target_states = target_states.view(opt.batch_size*opt.npred, -1)
        target_costs = target_costs.view(opt.batch_size*opt.npred, -1)
        latent_probs = latent_probs.view(opt.batch_size*opt.npred, -1)

        loss_i = utils.mdn_loss_fn(latent_probs, pred_images_sigma, pred_images_mu, target_images)

        pred_states_mu = pred_states[0].view(opt.batch_size*opt.npred, opt.n_mixture, -1)
        pred_states_sigma = pred_states[1].view(opt.batch_size*opt.npred, opt.n_mixture, -1)
        loss_s = utils.mdn_loss_fn(latent_probs, pred_states_sigma, pred_states_mu, target_states)

        pred_costs_mu = pred_costs[0].view(opt.batch_size*opt.npred, opt.n_mixture, -1)
        pred_costs_sigma = pred_costs[1].view(opt.batch_size*opt.npred, opt.n_mixture, -1)
        loss_c = utils.mdn_loss_fn(latent_probs, pred_costs_sigma, pred_costs_mu, target_costs)

    else:
        pred_images, pred_states, pred_costs = predictions
        loss_i = F.mse_loss(pred_images, target_images, reduce=r)
        loss_s = F.mse_loss(pred_states, target_states, reduce=r)
        loss_c = F.mse_loss(pred_costs, target_costs, reduce=r)
    return loss_i, loss_s, loss_c
    

# loss_i: images
# loss_s: states
# loss_c: costs
# loss_p: prior

def make_variables(x):
    y = []
    for i in range(len(x)):
        y.append(Variable(x[i]))
    return y

def train(nbatches, npred):
    model.train()
    total_loss_i, total_loss_s, total_loss_c, total_loss_p = 0, 0, 0, 0
    for i in range(nbatches):
        optimizer.zero_grad()
        t0 = time.time()
        inputs, actions, targets = dataloader.get_batch_fm('train', npred)
        inputs = make_variables(inputs)
        targets = make_variables(targets)
        actions = Variable(actions)
        if opt.zeroact == 1:
            actions.data.zero_()
        pred, loss_p = model(inputs, actions, targets)
        loss_i, loss_s, loss_c = compute_loss(targets, pred)
        loss = loss_i + loss_s + loss_c + opt.beta * loss_p
        loss.backward()
        if opt.model == 'fwd-cnn-mdn':
            torch.nn.utils.clip_grad_norm(model.parameters(), 50)
        optimizer.step()
        t = time.time()-t0
        total_loss_i += loss_i.data[0]
        total_loss_s += loss_s.data[0]
        total_loss_c += loss_c.data[0]
        total_loss_p += loss_p.data[0]
        del inputs, actions, targets

    total_loss_i /= nbatches
    total_loss_s /= nbatches
    total_loss_c /= nbatches
    total_loss_p /= nbatches
    return total_loss_i, total_loss_s, total_loss_c, total_loss_p


def test(nbatches):
    model.eval()
    total_loss_i, total_loss_s, total_loss_c, total_loss_p = 0, 0, 0, 0
    for i in range(nbatches):
        inputs, actions, targets = dataloader.get_batch_fm('valid')
        inputs = make_variables(inputs)
        targets = make_variables(targets)
        actions = Variable(actions)
        if opt.zeroact == 1:
            actions.data.zero_()
        pred, loss_p = model(inputs, actions, targets)
        loss_i, loss_s, loss_c = compute_loss(targets, pred)
        total_loss_i += loss_i.data[0]
        total_loss_s += loss_s.data[0]
        total_loss_c += loss_c.data[0]
        total_loss_p += loss_p.data[0]
        del inputs, actions, targets

    total_loss_i /= nbatches
    total_loss_s /= nbatches
    total_loss_c /= nbatches
    total_loss_p /= nbatches
    return total_loss_i, total_loss_s, total_loss_c, total_loss_p


def compute_pz(nbatches):
    model.p_z = []
    for j in range(nbatches):
        inputs, actions, targets, _, _ = dataloader.get_batch_fm('train', opt.npred)
        inputs = Variable(inputs)
        actions = Variable(actions)
        targets = Variable(targets)
        pred, loss_kl = model(inputs, actions, targets, save_z = True)
        

optimizer = optim.Adam(model.parameters(), opt.lrt)
print('[training]')
best_total_valid_loss = 1e6
for i in range(100):
    t0 = time.time()
    train_losses = train(opt.epoch_size, opt.npred)
    valid_losses = test(int(opt.epoch_size / 2))
    t = time.time() - t0
    total_valid_loss = 0
    for loss in valid_losses:
        total_valid_loss += loss
    if total_valid_loss < best_total_valid_loss:
        best_total_valid_loss = total_valid_loss
        model.intype('cpu')
        torch.save(model, opt.model_file + '.model')
        model.intype('gpu')
    log_string = f'step {(i+1)*opt.epoch_size} | '
    log_string += utils.format_losses(*train_losses, 'train')
    log_string += utils.format_losses(*valid_losses, 'valid')
    print(log_string)
    utils.log(opt.model_file + '.log', log_string)

