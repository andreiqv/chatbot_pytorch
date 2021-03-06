#
#
#
# if there's a problem with encoding: 
# export PYTHONIOENCODING=utf-8

import torch
import os
import sys
import argparse
import settings
from settings import *
from model import *
from voc import *

def maskNLLLoss(inp, target, mask):
	nTotal = mask.sum()
	crossEntropy = -torch.log(torch.gather(inp, 1, target.view(-1, 1)).squeeze(1))
	loss = crossEntropy.masked_select(mask).mean()
	loss = loss.to(device)
	return loss, nTotal.item()

def train(input_variable, lengths, target_variable, mask, max_target_len, encoder, decoder, embedding,
		  encoder_optimizer, decoder_optimizer, batch_size, clip, max_length=MAX_LENGTH):

	# Zero gradients
	encoder_optimizer.zero_grad()
	decoder_optimizer.zero_grad()

	# Set device options
	input_variable = input_variable.to(device)
	lengths = lengths.to(device)
	target_variable = target_variable.to(device)
	mask = mask.to(device)

	# Initialize variables
	loss = 0
	print_losses = []
	n_totals = 0

	# Forward pass through encoder
	encoder_outputs, encoder_hidden = encoder(input_variable, lengths)

	# Create initial decoder input (start with SOS tokens for each sentence)
	decoder_input = torch.LongTensor([[SOS_token for _ in range(batch_size)]])
	decoder_input = decoder_input.to(device)

	# Set initial decoder hidden state to the encoder's final hidden state
	decoder_hidden = encoder_hidden[:decoder.n_layers]

	# Determine if we are using teacher forcing this iteration
	use_teacher_forcing = True if random.random() < teacher_forcing_ratio else False

	# Forward batch of sequences through decoder one time step at a time
	if use_teacher_forcing:
		for t in range(max_target_len):
			decoder_output, decoder_hidden = decoder(
				decoder_input, decoder_hidden, encoder_outputs
			)
			# Teacher forcing: next input is current target
			decoder_input = target_variable[t].view(1, -1)
			# Calculate and accumulate loss
			mask_loss, nTotal = maskNLLLoss(decoder_output, target_variable[t], mask[t])
			loss += mask_loss
			print_losses.append(mask_loss.item() * nTotal)
			n_totals += nTotal
	else:
		for t in range(max_target_len):
			decoder_output, decoder_hidden = decoder(
				decoder_input, decoder_hidden, encoder_outputs
			)
			# No teacher forcing: next input is decoder's own current output
			_, topi = decoder_output.topk(1)
			decoder_input = torch.LongTensor([[topi[i][0] for i in range(batch_size)]])
			decoder_input = decoder_input.to(device)
			# Calculate and accumulate loss
			mask_loss, nTotal = maskNLLLoss(decoder_output, target_variable[t], mask[t])
			loss += mask_loss
			print_losses.append(mask_loss.item() * nTotal)
			n_totals += nTotal

	# Perform backpropatation
	loss.backward()

	# Clip gradients: gradients are modified in place
	_ = torch.nn.utils.clip_grad_norm_(encoder.parameters(), clip)
	_ = torch.nn.utils.clip_grad_norm_(decoder.parameters(), clip)

	# Adjust model weights
	encoder_optimizer.step()
	decoder_optimizer.step()

	return sum(print_losses) / n_totals


def trainIters(model_name, voc, pairs, encoder, decoder, encoder_optimizer, 
	decoder_optimizer, embedding, encoder_n_layers, decoder_n_layers, save_dir, 
	n_iteration, batch_size, print_every, save_every, clip, corpus_name, loadFilename):

	# Load batches for each iteration
	training_batches = [batch2TrainData(voc, [random.choice(pairs) for _ in range(batch_size)])
					  for _ in range(n_iteration)]

	# Initializations
	print('Initializing ...')
	start_iteration = 1
	print_loss = 0
	if loadFilename:
		start_iteration = checkpoint['iteration'] + 1

	# Training loop
	print("Training...")
	for iteration in range(start_iteration, n_iteration + 1):
		training_batch = training_batches[iteration - 1]
		# Extract fields from batch
		input_variable, lengths, target_variable, mask, max_target_len = training_batch

		# Run a training iteration with batch
		loss = train(input_variable, lengths, target_variable, mask, max_target_len, encoder,
					 decoder, embedding, encoder_optimizer, decoder_optimizer, batch_size, clip)
		print_loss += loss

		# Print progress
		if iteration % print_every == 0:
			print_loss_avg = print_loss / print_every
			print("Iteration: {}; Percent complete: {:.1f}%; Average loss: {:.4f}".format(iteration, iteration / n_iteration * 100, print_loss_avg))
			print_loss = 0

		# Save checkpoint
		if (iteration % save_every == 0):
			directory = os.path.join(save_dir, model_name, corpus_name, '{}-{}_{}'.format(encoder_n_layers, decoder_n_layers, hidden_size))
			if not os.path.exists(directory):
				os.makedirs(directory)
			torch.save({
				'iteration': iteration,
				'en': encoder.state_dict(),
				'de': decoder.state_dict(),
				'en_opt': encoder_optimizer.state_dict(),
				'de_opt': decoder_optimizer.state_dict(),
				'loss': loss,
				'voc_dict': voc.__dict__,
				'embedding': embedding.state_dict()
			}, os.path.join(directory, '{}_{}.tar'.format(iteration, 'checkpoint')))

#---------------

class GreedySearchDecoder(nn.Module):
	def __init__(self, encoder, decoder):
		super(GreedySearchDecoder, self).__init__()
		self.encoder = encoder
		self.decoder = decoder

	def forward(self, input_seq, input_length, max_length):
		# Forward input through encoder model
		encoder_outputs, encoder_hidden = self.encoder(input_seq, input_length)
		# Prepare encoder's final hidden layer to be first hidden input to the decoder
		decoder_hidden = encoder_hidden[:decoder.n_layers]
		# Initialize decoder input with SOS_token
		decoder_input = torch.ones(1, 1, device=device, dtype=torch.long) * SOS_token
		# Initialize tensors to append decoded words to
		all_tokens = torch.zeros([0], device=device, dtype=torch.long)
		all_scores = torch.zeros([0], device=device)
		# Iteratively decode one word token at a time
		for _ in range(max_length):
			# Forward pass through decoder
			decoder_output, decoder_hidden = self.decoder(decoder_input, decoder_hidden, encoder_outputs)
			# Obtain most likely word token and its softmax score
			decoder_scores, decoder_input = torch.max(decoder_output, dim=1)
			# Record token and score
			all_tokens = torch.cat((all_tokens, decoder_input), dim=0)
			all_scores = torch.cat((all_scores, decoder_scores), dim=0)
			# Prepare current token to be next decoder input (add a dimension)
			decoder_input = torch.unsqueeze(decoder_input, 0)
		# Return collections of word tokens and scores
		return all_tokens, all_scores


#---------

def evaluate(encoder, decoder, searcher, voc, sentence, max_length=MAX_LENGTH):
	### Format input sentence as a batch
	# words -> indexes
	indexes_batch = [indexesFromSentence(voc, sentence)]
	# Create lengths tensor
	lengths = torch.tensor([len(indexes) for indexes in indexes_batch])
	# Transpose dimensions of batch to match models' expectations
	input_batch = torch.LongTensor(indexes_batch).transpose(0, 1)
	# Use appropriate device
	input_batch = input_batch.to(device)
	lengths = lengths.to(device)
	# Decode sentence with searcher
	tokens, scores = searcher(input_batch, lengths, max_length)
	# indexes -> words
	decoded_words = [voc.index2word[token.item()] for token in tokens]
	return decoded_words


def evaluateInput(encoder, decoder, searcher, voc):
	input_sentence = ''
	while(1):
		try:
			# Get input sentence
			input_sentence = input('> ')
			# Check if it is quit case
			if input_sentence == 'q' or input_sentence == 'quit': break
			# Normalize sentence
			input_sentence = normalizeString(input_sentence)
			#print('normalized_input_sentence:', input_sentence)
			# Evaluate sentence
			output_words = evaluate(encoder, decoder, searcher, voc, input_sentence)
			# Format and print response sentence
			output_words[:] = [x for x in output_words if not (x == 'EOS' or x == 'PAD')]
			print('Bot:', ' '.join(output_words))

		except KeyError:
			print("Error: Encountered unknown word.")


def evaluateExample(encoder, decoder, searcher, voc, sentence):
	""" The function takes a string input sentence as an argument, 
	normalizes it, evaluates it, and prints the response.
	"""
	print("\n> " + sentence)
	# Normalize sentence
	try:
		input_sentence = normalizeString(sentence)
		# Evaluate sentence
		output_words = evaluate(encoder, decoder, searcher, voc, input_sentence)
		output_words[:] = [x for x in output_words if not (x == 'EOS' or x == 'PAD')]
		print('Bot:', ' '.join(output_words))
	except KeyError:
		print("Error: Encountered unknown word.")		

#------------

def createParser ():
	"""
	ArgumentParser
	"""
	parser = argparse.ArgumentParser()
	parser.add_argument('-train', '--train', dest='train', action='store_true')
	parser.add_argument('-eval', '--eval', dest='eval', action='store_true')
	parser.add_argument('-iter', '--iter', default=0, type=int,\
		help='iter number')	
	return parser


if __name__ == '__main__':

	parser = createParser()
	arguments = parser.parse_args(sys.argv[1:])			
	#print('set arguments.tests =', arguments.tests)
	#if arguments.eval:
	#	loadFilename = loadFilename = os.path.join(save_dir, 'cb_model/corpus/2-2_500/50000_checkpoint.tar')
	#else:
	#	loadFilename = None

	# ---------
	# Run Model

	# Configure models
	model_name = 'cb_model'
	attn_model = 'dot'
	#attn_model = 'general'
	#attn_model = 'concat'
	hidden_size = 500
	encoder_n_layers = 2
	decoder_n_layers = 2
	dropout = 0.1
	batch_size = 128 #64

	# Set checkpoint to load from; set to None if starting from scratch
	checkpoint_iter = 4000

	if arguments.eval:
		#loadFilename = loadFilename = os.path.join(save_dir, 'cb_model/corpus/2-2_500/50000_checkpoint.tar')
		loadFilename = os.path.join(save_dir, model_name, corpus_name,
							'{}-{}_{}'.format(encoder_n_layers, decoder_n_layers, hidden_size),
							'{}_checkpoint.tar'.format(checkpoint_iter))	
	else:
		loadFilename = None	
	#loadFilename = None	
	#loadFilename = os.path.join(save_dir, model_name, corpus_name,
	#							'{}-{}_{}'.format(encoder_n_layers, decoder_n_layers, hidden_size),
	#							'{}_checkpoint.tar'.format(checkpoint_iter))


	# Load model if a loadFilename is provided
	if loadFilename:
		# If loading on same machine the model was trained on
		checkpoint = torch.load(loadFilename)
		# If loading a model trained on GPU to CPU
		#checkpoint = torch.load(loadFilename, map_location=torch.device('cpu'))
		encoder_sd = checkpoint['en']
		decoder_sd = checkpoint['de']
		encoder_optimizer_sd = checkpoint['en_opt']
		decoder_optimizer_sd = checkpoint['de_opt']
		embedding_sd = checkpoint['embedding']
		voc.__dict__ = checkpoint['voc_dict']


	print('Building encoder and decoder ...')
	# Initialize word embeddings
	embedding = nn.Embedding(voc.num_words, hidden_size)
	# Initialize encoder & decoder models
	encoder = EncoderRNN(hidden_size, embedding, encoder_n_layers, dropout)
	decoder = LuongAttnDecoderRNN(attn_model, embedding, hidden_size, voc.num_words, decoder_n_layers, dropout)
	if loadFilename:
		embedding.load_state_dict(embedding_sd)
		encoder.load_state_dict(encoder_sd)
		decoder.load_state_dict(decoder_sd)

	# Use appropriate device
	encoder = encoder.to(device)
	decoder = decoder.to(device)
	print('Models built and ready to go!')

	# ------ 
	# Run Training 
	if arguments.train:

		# Configure training/optimization
		clip = 50.0
		teacher_forcing_ratio = 1.0
		learning_rate = 0.0001
		decoder_learning_ratio = 5.0
		n_iteration = arguments.iter if arguments.iter > 0 else 4000
		save_every  = n_iteration / 1
		print_every = 1

		# Ensure dropout layers are in train mode
		encoder.train()
		decoder.train()

		# Initialize optimizers
		print('Building optimizers ...')
		encoder_optimizer = optim.Adam(encoder.parameters(), lr=learning_rate)
		decoder_optimizer = optim.Adam(decoder.parameters(), lr=learning_rate * decoder_learning_ratio)
		if loadFilename:
			encoder_optimizer.load_state_dict(encoder_optimizer_sd)
			decoder_optimizer.load_state_dict(decoder_optimizer_sd)

		# Run training iterations
		print("Starting Training!")
		trainIters(model_name, voc, pairs, encoder, decoder, 
					encoder_optimizer, decoder_optimizer, 
					embedding, encoder_n_layers, decoder_n_layers, save_dir, 
					n_iteration, batch_size, print_every, save_every, clip, 
					corpus_name, loadFilename)


		#os.system('mkdir -p save')
		#torch.save(encoder, 'save/encoder')
		#torch.save(decoder, 'save/decoder')

	#-----------
	# evaluation:

	# Set dropout layers to eval mode
	encoder.eval()
	decoder.eval()

	# Initialize search module
	searcher = GreedySearchDecoder(encoder, decoder)

	with open(testfile, encoding='utf8') as fp:
		for line in fp:
			sentence = line.strip()
			evaluateExample(encoder, decoder, searcher, voc, sentence)

	# Begin chatting (uncomment and run the following line to begin)
	#evaluateInput(encoder, decoder, searcher, voc)
			