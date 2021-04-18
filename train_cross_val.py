from __future__ import print_function

import random
import tensorflow as tf
import numpy as np
import os, argparse, pathlib

from eval import eval
from data_cross_val import BalanceCovidDataset
from sklearn.model_selection import KFold, StratifiedKFold

def _process_csv_file(file):
    with open(file, 'r') as fr:
        files = fr.readlines()
    return np.array(files)

# To remove TF Warnings
tf.compat.v1.logging.set_verbosity(tf.compat.v1.logging.ERROR)
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '2'

parser = argparse.ArgumentParser(description='COVID-Net Training Script')
parser.add_argument('--epochs', default=50, type=int, help='Number of epochs')
parser.add_argument('--lr', default=0.0002, type=float, help='Learning rate')
parser.add_argument('--bs', default=8, type=int, help='Batch size')
parser.add_argument('--weightspath', default='/home/maya.pavlova/covidnet-orig/models/COVIDNet-CXR-2', type=str, help='Path to model files, defaults to \'models/COVIDNet-CXR-2\'')
parser.add_argument('--metaname', default='model.meta', type=str, help='Name of ckpt meta file')
parser.add_argument('--ckptname', default='model', type=str, help='Name of model ckpts')
parser.add_argument('--n_classes', default=2, type=int, help='Number of detected classes, defaults to 2')
parser.add_argument('--file', default='/home/maya.pavlova/covidnet-orig/hospital_data.txt', type=str, help='Path to train file')
parser.add_argument('--name', default='COVIDNet', type=str, help='Name of folder to store training checkpoints')
parser.add_argument('--datadir', default='/home/maya.pavlova/covidnet-orig/hospital_images', type=str, help='Path to data folder')
parser.add_argument('--covid_weight', default=1., type=float, help='Class weighting for covid')
parser.add_argument('--covid_percent', default=0.3, type=float, help='Percentage of covid samples in batch')
parser.add_argument('--input_size', default=480, type=int, help='Size of input (ex: if 480x480, --input_size 480)')
parser.add_argument('--top_percent', default=0.08, type=float, help='Percent top crop from top of image')
parser.add_argument('--in_tensorname', default='input_1:0', type=str, help='Name of input tensor to graph')
parser.add_argument('--out_tensorname', default='norm_dense_2/Softmax:0', type=str, help='Name of output tensor from graph')
parser.add_argument('--logit_tensorname', default='norm_dense_2/MatMul:0', type=str, help='Name of logit tensor for loss')
parser.add_argument('--label_tensorname', default='norm_dense_1_target:0', type=str, help='Name of label tensor for loss')
parser.add_argument('--weights_tensorname', default='norm_dense_1_sample_weights:0', type=str, help='Name of sample weights tensor for loss')


args = parser.parse_args()

# Parameters
learning_rate = args.lr
batch_size = args.bs
display_step = 1

if args.n_classes == 2:
    # For COVID-19 positive/negative detection
    mapping = {
        'negative': 0,
        'positive': 1,
    }
    class_weights = [1., args.covid_weight]
elif args.n_classes == 3:
    # For detection of no pneumonia/non-COVID-19 pneumonia/COVID-19 pneumonia
    mapping = {
        'normal': 0,
        'pneumonia': 1,
        'COVID-19': 2
    }
    class_weights = [1., 1., args.covid_weight]
else:
    raise Exception('''COVID-Net currently only supports 2 class COVID-19 positive/negative detection
        or 3 class detection of no pneumonia/non-COVID-19 pneumonia/COVID-19 pneumonia''')

# Set up folds
fold_number=5
files = list(_process_csv_file(args.file))
classes=[element.split(" ")[-1][:-1] for element in files]


print("creating balanced negative percentage")
list_negative=[]
preserved_neg=[]
for i in range(len(classes)):
    if(classes[i]=="negative"):
        list_negative.append(i)
print(list_negative)
list_negative.sort(reverse=True)
for index in list_negative:
    preserved_neg.append(files[index])
    del classes[index]
    del files[index]
random.shuffle(list_negative)
step_size=int(np.floor(len(preserved_neg)/fold_number))
chunks_neg = [preserved_neg[x:x + step_size] for x in range(0, len(preserved_neg), step_size)]
if(len(chunks_neg)>fold_number):
    chunks_neg[-1]= chunks_neg[-1] + chunks_neg[-2]
    del chunks_neg[-2]

kf = KFold(n_splits=fold_number, random_state=42, shuffle=True)

with tf.Session() as sess:
    tf.get_default_graph()
    saver = tf.train.import_meta_graph(os.path.join(args.weightspath, args.metaname))
    saver = tf.train.Saver(max_to_keep=100)

    graph = tf.get_default_graph()

    image_tensor = graph.get_tensor_by_name(args.in_tensorname)
    labels_tensor = graph.get_tensor_by_name(args.label_tensorname)
    sample_weights = graph.get_tensor_by_name(args.weights_tensorname)
    pred_tensor = graph.get_tensor_by_name(args.logit_tensorname)
    # loss expects unscaled logits since it performs a softmax on logits internally for efficiency

    # Define loss and optimizer
    loss_op = tf.reduce_mean(tf.nn.softmax_cross_entropy_with_logits_v2(
        logits=pred_tensor, labels=labels_tensor)*sample_weights)
    optimizer = tf.train.AdamOptimizer(learning_rate=learning_rate)
    train_op = optimizer.minimize(loss_op)

    for fold_num, (train_i, test_i) in enumerate(kf.split(files)):
        print('Training fold number: ', fold_num)
        print('Length of train files: {}, Length of test files: {}'.format(len(train_i), len(test_i)))
        print('Train indexes: ', train_i)
        print()
        print('Test indexes: ', test_i)

        # output path
        outputPath = './output/'
        runID = args.name + '-file_num' + str(fold_num)
        runPath = outputPath + runID
        pathlib.Path(runPath).mkdir(parents=True, exist_ok=True)
        print('Output: ' + runPath)
        trainfiles = np.array(files)[train_i]
        trainfiles_neg = chunks_neg[fold_num][1:]
        testfiles = np.concatenate((np.array(files)[test_i],np.array(chunks_neg[fold_num][:1])))
        generator = BalanceCovidDataset(data_dir=args.datadir,
                                        files=trainfiles,
                                        neg_files=trainfiles_neg,
                                        batch_size=batch_size,
                                        input_shape=(args.input_size, args.input_size),
                                        n_classes=args.n_classes,
                                        mapping=mapping,
                                        covid_percent=args.covid_percent,
                                        class_weights=class_weights,
                                        top_percent=args.top_percent)

        # Initialize the variables
        init = tf.global_variables_initializer()

        # Run the initializer for every new k-fold run
        sess.run(init)

        # load weights
        saver.restore(sess, os.path.join(args.weightspath, args.ckptname))
        #saver.restore(sess, tf.train.latest_checkpoint(args.weightspath))

        # save base model
        saver.save(sess, os.path.join(runPath, 'model'))
        print('Saved baseline checkpoint')
        print('Baseline eval:')
        eval(sess, graph, testfiles, args.datadir,
            args.in_tensorname, args.out_tensorname, args.input_size, mapping)

        # Training cycle
        print('Training started')
        total_batch = len(generator)
        progbar = tf.keras.utils.Progbar(total_batch)
        for epoch in range(args.epochs):
            for i in range(total_batch):
                # Run optimization
                batch_x, batch_y, weights = next(generator)
                sess.run(train_op, feed_dict={image_tensor: batch_x,
                                            labels_tensor: batch_y,
                                            sample_weights: weights})
                progbar.update(i+1)

            if epoch % display_step == 0:
                pred = sess.run(pred_tensor, feed_dict={image_tensor:batch_x})
                loss = sess.run(loss_op, feed_dict={pred_tensor: pred,
                                                    labels_tensor: batch_y,
                                                    sample_weights: weights})
                print("Epoch:", '%04d' % (epoch + 1), "Minibatch loss=", "{:.9f}".format(loss))
                eval(sess, graph, testfiles, args.datadir,
                    args.in_tensorname, args.out_tensorname, args.input_size, mapping)
                saver.save(sess, os.path.join(runPath, 'model'), global_step=epoch+1, write_meta_graph=False)
                print('Saving checkpoint at epoch {}'.format(epoch + 1))


print("Optimization Finished!")
