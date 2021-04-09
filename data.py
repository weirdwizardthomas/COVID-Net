from tensorflow import keras
import tensorflow as tf
import pandas as pd
import datetime
from load_data import loadDataJSRT, loadDataJSRTSingle
import numpy as np
import os
import cv2

from tensorflow.keras.preprocessing.image import ImageDataGenerator

def crop_top(img, percent=0.15):
    offset = int(img.shape[0] * percent)
    return img[offset:]

def central_crop(img):
    size = min(img.shape[0], img.shape[1])
    offset_h = int((img.shape[0] - size) / 2)
    offset_w = int((img.shape[1] - size) / 2)
    return img[offset_h:offset_h + size, offset_w:offset_w + size]

def process_image_file(filepath, top_percent, size):
    img = cv2.imread(filepath)
    img = crop_top(img, percent=top_percent)
    img = central_crop(img)
    img = cv2.resize(img, (size, size))
    return img

def random_ratio_resize(img, prob=0.3, delta=0.1):
    if np.random.rand() >= prob:
        return img
    ratio = img.shape[0] / img.shape[1]
    ratio = np.random.uniform(max(ratio - delta, 0.01), ratio + delta)

    if ratio * img.shape[1] <= img.shape[1]:
        size = (int(img.shape[1] * ratio), img.shape[1])
    else:
        size = (img.shape[0], int(img.shape[0] / ratio))

    dh = img.shape[0] - size[1]
    top, bot = dh // 2, dh - dh // 2
    dw = img.shape[1] - size[0]
    left, right = dw // 2, dw - dw // 2

    if size[0] > 480 or size[1] > 480:
        print(img.shape, size, ratio)

    img = cv2.resize(img, size)
    img = cv2.copyMakeBorder(img, top, bot, left, right, cv2.BORDER_CONSTANT,
                             (0, 0, 0))

    if img.shape[0] != 480 or img.shape[1] != 480:
        raise ValueError(img.shape, size)
    return img

_augmentation_transform = ImageDataGenerator(
    featurewise_center=False,
    featurewise_std_normalization=False,
    rotation_range=10,
    width_shift_range=0.1,
    height_shift_range=0.1,
    horizontal_flip=True,
    brightness_range=(0.9, 1.1),
    zoom_range=(0.85, 1.15),
    fill_mode='constant',
    cval=0.,
)

def apply_augmentation(img):
    img = random_ratio_resize(img)
    img = _augmentation_transform.random_transform(img)
    return img

def _process_csv_file(file):
    with open(file, 'r') as fr:
        files = fr.readlines()
    return files


class BalanceCovidDataset(keras.utils.Sequence):
    'Generates data for Keras'

    def __init__(
            self,
            data_dir,
            csv_file,
            is_training=True,
            batch_size=8,
            input_shape=(224, 224),
            n_classes=3,
            num_channels=3,
            shuffle=True,
            augmentation=apply_augmentation,
            covid_percent=0.3,
            class_weights=[1., 1., 6.],
            top_percent=0.08,
            col_name=[],
            target_name="",
            width_semantic=256
    ):
        'Initialization'

        self.datadir = data_dir
        self.dataset = _process_csv_file(csv_file)
        self.is_training = is_training
        self.batch_size = batch_size
        self.N = len(self.dataset)
        self.input_shape = input_shape
        self.n_classes = 0
        self.num_channels = num_channels
        self.mapping = {}
        self.shuffle = True
        self.covid_percent = covid_percent
        self.class_weights = class_weights
        flag_empty_weight=True if len(self.class_weights)==0 else False
        self.n = 0
        self.augmentation = augmentation
        self.top_percent = top_percent
        self.width_semantic=width_semantic
        self.datasets = []
        self.mapping={}
        self.classes_data=[]
        df = pd.read_csv(csv_file, delimiter=" ",names=col_name)
        result=df[target_name].value_counts()
        for element in list(df[target_name].unique()):
            if element not in ["None"]:
                self.datasets.extend(df.loc[df[target_name] == element][["img_path",target_name]].values)
                self.mapping[element]=self.n_classes
                self.classes_data.append(df.loc[df[target_name] == element][["img_path",target_name]].values)
                if(flag_empty_weight):
                    self.class_weights.append(1-result[element]/sum(result))
                if(element=="Mild"):
                    self.class_weights[self.n_classes]=2
                self.n_classes+=1
        self.datasets=np.array(self.datasets)
        self.on_epoch_end()
        print(self.mapping)

    def __next__(self):
        # Get one batch of data
        batch_x, batch_y, weights = self.__getitem__(self.n)
        # Batch index
        self.n += 1

        # If we have processed the entire dataset then
        if self.n >= self.__len__():
            self.on_epoch_end()
            self.n = 0

        return batch_x, batch_y, weights

    def __len__(self):
        return int(np.ceil(len(self.datasets) / float(self.batch_size)))

    def on_epoch_end(self):
        'Updates indexes after each epoch'
        if self.shuffle == True:
            np.random.shuffle(self.datasets)
            for element in self.classes_data:
                np.random.shuffle(element)

    def create_balance_batch(self,size):
        sample_per_class=np.floor(size/len(self.classes_data))
        samples=[]
        for i in range(len(self.classes_data)):
            samples.extend(list(self.classes_data[i][np.random.choice((self.classes_data[i]).shape[0], int(sample_per_class), replace=False)]))
        if(len(samples)<size):
            samples.extend(list(self.datasets[np.random.choice(self.datasets.shape[0], size-len(samples), replace=False)]))
        return samples


    def __getitem__(self, idx):
        batch_x, batch_y = np.zeros(
            (self.batch_size,2, *self.input_shape,
             self.num_channels)), np.zeros(self.batch_size)
        samples=self.create_balance_batch(self.batch_size)

        for i,sample in enumerate(samples):
            x = process_image_file(os.path.join(self.datadir, sample[0]),
                                   self.top_percent,
                                   self.input_shape[0])

            x1= loadDataJSRTSingle(os.path.join(self.datadir, sample[0]),
                                   (self.width_semantic,self.width_semantic))

            if self.is_training and hasattr(self, 'augmentation'):
                x = self.augmentation(x)


            x = x.astype('float32') / 255.0
            y = self.mapping[sample[1]]

            batch_x[i][0] = x
            batch_x[i][1][:self.width_semantic,:self.width_semantic,:1]= x1
            batch_y[i] = y

        class_weights = self.class_weights
        weights = np.take(class_weights, batch_y.astype('int64'))

        return tf.cast(batch_x,tf.float32), keras.utils.to_categorical(batch_y, num_classes=self.n_classes), weights
