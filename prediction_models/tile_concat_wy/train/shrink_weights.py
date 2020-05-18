import torch
weights = [f'./weights/Resnext50_30epoch/Resnext50_30epoch_{i}_best.pth.tar' for i in range(5)]
state_dict = torch.load(weights[0])
weights_state = state_dict['state_dict']
torch.save(weights_state, 'f./weights/Resnext50_30epoch/Resnext50_30epoch_0_little.pth')