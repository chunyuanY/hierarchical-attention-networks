#!/usr/bin/env python3
import argparse
import importlib
import os
import pickle
import random
from collections import defaultdict

import ujson
import numpy as np
import spacy
import tensorflow as tf
from tensorflow.contrib.tensorboard.plugins import projector
from tqdm import tqdm

from bn_lstm import BNLSTMCell
from data_util import batch
from model import TextClassifierModel

try:
  from tensorflow.contrib.rnn import GRUCell, MultiRNNCell
except ImportError:
  MultiRNNCell = tf.nn.rnn_cell.MultiRNNCell
  GRUCell = tf.nn.rnn_cell.GRUCell

parser = argparse.ArgumentParser()
parser.add_argument('task')
parser.add_argument('mode', choices=['train', 'eval'])
parser.add_argument('--checkpoint-frequency', type=int, default=100)
parser.add_argument('--batch-size', type=int, default=100)
args = parser.parse_args()

task = importlib.import_module(args.task)

device = '/cpu:0'
checkpoint_dir = os.path.join(task.train_dir, 'checkpoint')
tflog_dir = os.path.join(task.train_dir, 'tflog')

checkpoint_name = args.task + '-model'
checkpoint_dir = os.path.join(task.train_dir, 'checkpoints')
checkpoint_path = os.path.join(checkpoint_dir, checkpoint_name)

trainset = task.read_trainset()
devset = task.read_devset()
vocab = task.read_vocab()
labels = task.read_labels()

labels_rev = {int(v): k for k, v in labels.items()}
vocab_rev = {int(v): k for k, v in vocab.items()}

def decode(ex):
  print('text: ' + '\n'.join([' '.join([vocab_rev.get(wid, '<?>') for wid in sent]) for sent in ex[0]]))
  print('label: ', labels_rev[ex[1]])

# import IPython
# IPython.embed()

def batch_iterator(dataset, batch_size, max_epochs):
  for i in range(max_epochs):
    xb = []
    yb = []
    for ex in dataset:
      x, y = ex
      xb.append(x)
      yb.append(y)
      if len(xb) == batch_size:
        yield xb, yb
        xb, yb = [], []
    print('epoch %s over' % i)

def create_model(session, restore_only=False):
  is_training = tf.placeholder(dtype=tf.bool, name='is_training')

  cell = BNLSTMCell(80, is_training) # h-h batchnorm LSTMCell
  # cell = GRUCell(80)
  cell = MultiRNNCell([cell]*5)

  model = TextClassifierModel(
    vocab_size=10000,
    embedding_size=200,
    classes=len(labels),
    word_cell=cell,
    sentence_cell=cell,
    word_output_size=100,
    sentence_output_size=100,
    device=device,
    learning_rate=1e-4,
    max_grad_norm=15.0,
    dropout_keep_proba=0.5,
    is_training=is_training,
  )

  saver = tf.train.Saver(tf.global_variables())
  checkpoint = tf.train.get_checkpoint_state(checkpoint_dir)
  if checkpoint:
    print("Reading model parameters from %s" % checkpoint.model_checkpoint_path)
    saver.restore(session, checkpoint.model_checkpoint_path)
  elif restore_only:
    raise FileNotFoundError("Cannot restore model")
  else:
    print("Created model with fresh parameters")
    session.run(tf.global_variables_initializer())
  tf.get_default_graph().finalize()
  return model, saver

def evaluate():
  tf.reset_default_graph()

  config = tf.ConfigProto(allow_soft_placement=True)

  with tf.Session(config=config) as s:
    model, saver = create_model(s, restore_only=True)
    print('evaluating model on the dev set')

    for x, y in batch_iterator(devset, args.batch_size, 300):
      fd = model.get_feed_data(x)
      prediction = s.run(model.prediction, fd)

      import IPython
      IPython.embed()

def train():
  tf.reset_default_graph()

  config = tf.ConfigProto(allow_soft_placement=True)

  with tf.Session(config=config) as s:
    model, saver = create_model(s)
    summary_writer = tf.summary.FileWriter(tflog_dir, graph=tf.get_default_graph())

    # Format: tensorflow/contrib/tensorboard/plugins/projector/projector_config.proto
    # pconf = projector.ProjectorConfig()

    # # You can add multiple embeddings. Here we add only one.
    # embedding = pconf.embeddings.add()
    # embedding.tensor_name = m.embedding_matrix.name

    # # Link this tensor to its metadata file (e.g. labels).
    # embedding.metadata_path = vocab_tsv

    # print(embedding.tensor_name)

    # Saves a configuration file that TensorBoard will read during startup.

    for i, (x, y) in enumerate(batch_iterator(trainset, args.batch_size, 300)):
      fd = model.get_feed_data(x, y)
      step, summaries, loss, accuracy, _ = s.run([
        model.global_step,
        model.summary_op,
        model.loss,
        model.accuracy,
        model.train_op,
      ], fd)

      summary_writer.add_summary(summaries, global_step=step)
      # projector.visualize_embeddings(summary_writer, pconf)

      if i % 1 == 0:
        print('step %s, loss=%s, accuracy=%s' % (step, loss, accuracy))
      if i != 0 and i % args.checkpoint_frequency == 0:
        print('checkpoint & graph meta')
        saver.save(s, checkpoint_path, global_step=step)
        print('checkpoint done')
        # run_options = tf.RunOptions(trace_level=tf.RunOptions.FULL_TRACE)
        # run_metadata = tf.RunMetadata()
        # s.run([m.loss], feed_dict=fd, options=run_options, run_metadata=run_metadata)
        # summary_writer.add_run_metadata(run_metadata, 'step%d' % step)

def main():
  if args.mode == 'train':
    train()
  elif args.mode == 'eval':
    evaluate()

if __name__ == '__main__':
  main()
