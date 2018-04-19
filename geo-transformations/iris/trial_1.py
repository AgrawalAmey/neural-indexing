
# coding: utf-8

# In[1]:


import itertools
import os
import sys

from keras import backend as K
from keras.callbacks import TensorBoard, ModelCheckpoint, Callback
from keras.datasets import cifar10
from keras.layers import Add, AveragePooling2D, BatchNormalization, Concatenate, Conv2D, Dense, Input, Lambda, MaxPooling2D, Reshape, UpSampling2D
from keras.models import Model
from keras.optimizers import SGD
from keras.utils import multi_gpu_model
import matplotlib.pyplot as plt
import numpy as np
import tensorflow as tf
from tensorflow.python import debug as tf_debug
import time
import visdom

# In[2]:


#os.environ["CUDA_VISIBLE_DEVICES"] = "0"


# In[3]:


# debugging
# K.set_session(tf_debug.TensorBoardDebugWrapperSession(K.get_session(),
#                                                       'localhost:6064',
#                                                       send_traceback_and_source_code=False))


# In[3]:


def decode(serialized_example):
    """Parses an image and label from the given `serialized_example`."""
    features = tf.parse_single_example(
        serialized_example,
        # Defaults are not specified since both keys are required.
        features={
            'label': tf.FixedLenFeature([], tf.int64),
            'image': tf.FixedLenFeature([], tf.string),
        })

    # Convert from a scalar string tensor (whose single string has
    # length 250 * 250) to a float64 tensor with shape
    # [250 * 250].
    image = tf.decode_raw(features['image'], tf.float32)
    image = tf.reshape(image, [64, 512, 1])
    
    # Remove NaN
    image = tf.where(tf.is_nan(image), tf.zeros_like(image), image)
    
    # Normalize image     
    image = (image + 0.49) * 500 + 4.5
    
    # Convert label from a scalar uint8 tensor to an int32 scalar.
    label = tf.cast(features['label'], tf.int64)
    
    return image, label


# In[4]:


def translate(image, label, num_samples=5, num_quantums=16):
    transformed_images = []
    translate_vectors = []

    for _ in range(num_samples):
        translation_index = np.random.randint(0, num_quantums)
        translation = translation_index * (512 // num_quantums)
        transformed_images.append(
            tf.concat([image[:, translation:],
                       image[:, :translation]], 1))
        translate_vector = np.zeros(num_quantums, np.uint16)
        translate_vector[translation_index] = 1
        translate_vector = tf.convert_to_tensor(translate_vector)
        translate_vectors.append(translate_vector)

    images = tf.stack([image] * num_samples)
    labels = tf.stack([label] * num_samples)
    transformed_images = tf.stack(transformed_images)
    translate_vectors = tf.stack(translate_vectors)

    return images, labels, transformed_images, translate_vectors


# In[5]:


translate_lambda = lambda image, label: translate(image, label)


# In[6]:


def inputs(sess, file_pattern, batch_size, num_epochs):
    """Reads input data num_epochs times.
    Args:
    batch_size: Number of examples per returned batch.
    num_epochs: Number of times to read the input data, or 0/None to
       train forever.
    Returns:
    A tuple (images, labels), where:
    * images is a float tensor with shape [batch_size, 350, 250]
      in the range [-0.5, 0.5].
    * labels is an int64 tensor with shape [batch_size] with the true label.

    This function creates a one_shot_iterator, meaning that it will only iterate
    over the dataset once. On the other hand there is no special initialization
    required.
    """
    if not num_epochs:
        num_epochs = None

    with tf.name_scope('input'):
        # Load multiple files by pattern
        files = tf.data.Dataset.list_files(file_pattern)

        dataset = files.apply(tf.contrib.data.parallel_interleave(
                                lambda filename: tf.data.TFRecordDataset(filename),
                                cycle_length=4,
                                block_length=4,
                                buffer_output_elements=batch_size))

        # Shuffle 500 elements at a time
        dataset = dataset.apply(
                        tf.contrib.data.shuffle_and_repeat(3 * batch_size, num_epochs))

        # Create batch and decode
#                          .map(translate, num_parallel_calls=4)\
#                          .apply(tf.contrib.data.unbatch())\
        dataset = dataset.map(decode, num_parallel_calls=4)                         .shuffle(batch_size * 5)                         .batch(batch_size)                         .prefetch(batch_size)

        iterator = dataset.make_one_shot_iterator()

        while True:
#             image, label, transformed_image, translate_vector = iterator.get_next()
#             image, label, transformed_image, translate_vector = sess.run([image, label, transformed_image, translate_vector])
#             yield ([image, translate_vector], transformed_image)
            image, _ = iterator.get_next()
            image  = sess.run([image])
            yield (image, image.copy())


# In[7]:


def show_samples_from_tfr(file_pattern):
    """Show sample images from a TFRecords file."""
    # Tell TensorFlow that the model will be built into the default Graph.
    with tf.Graph().as_default():
        # The op for initializing the variables.
        init_op = tf.group(tf.global_variables_initializer(),
                           tf.local_variables_initializer())

        # Create a session for running operations in the Graph.
        with tf.Session() as sess:
            # Initialize the variables (the trained variables and the
            # epoch counter).
            sess.run(init_op)

            gen = inputs(sess, file_pattern=file_pattern,
                                              batch_size=32, num_epochs=1)

            for image, label, transformed, translation_vector in gen:
                fig, axes = plt.subplots(nrows=8, ncols=2, figsize=(20, 10))
                print(transformed.mean(), transformed.std(), transformed.shape)
                for row in range(8):
                    axes[row, 0].axis("off")
                    axes[row, 1].axis("off")
                    axes[row, 0].imshow(image[row].reshape(64, 512))
                    axes[row, 0].set_title(label[row])
                    axes[row, 1].imshow(transformed[row].reshape(64, 512))
                    axes[row, 1].set_title(translation_vector[row].argmax())
                break


# In[34]:


#show_samples_from_tfr('../data/nd-iris-train-*.tfrecords')


# In[8]:


input_img = Input(shape=(64, 512, 1))
# shape_input = Input(shape=(16,))
# shape_input_reshaped = Reshape((1, 1, 16))(shape_input)

x = Conv2D(32, (7, 7), activation='relu', padding='same')(input_img)
x = BatchNormalization()(x)
x = Conv2D(64, (5, 5), activation='relu', padding='same')(x)
x = MaxPooling2D((2, 2))(x)

x = BatchNormalization()(x)
x = Conv2D(128, (3, 3), activation='relu', padding='same')(x)
x = BatchNormalization()(x)
x = Conv2D(192, (3, 3), activation='relu', padding='same')(x)
x = MaxPooling2D((2, 2))(x)

x = BatchNormalization()(x)
x = Conv2D(256, (3, 3), activation='relu', padding='same')(x)
x = BatchNormalization()(x)
x = Conv2D(320, (3, 3), activation='relu', padding='same')(x)
x = MaxPooling2D((2, 2))(x)

x = BatchNormalization()(x)
x = Conv2D(480, (3, 3), activation='relu', padding='same')(x)
x = BatchNormalization()(x)
x = Conv2D(512, (3, 3), activation='relu', padding='same')(x)
encoded = MaxPooling2D((2, 2))(x)

x = BatchNormalization()(encoded)
x = Conv2D(512, (3, 3), activation='relu', padding='same')(encoded)
x = BatchNormalization()(x)
x = Conv2D(480, (3, 3), activation='relu', padding='same')(x)
x = UpSampling2D((2, 2))(x)

x = BatchNormalization()(x)
x = Conv2D(320, (3, 3), activation='relu', padding='same')(x)
x = BatchNormalization()(x)
x = Conv2D(256, (3, 3), activation='relu', padding='same')(x)
x = UpSampling2D((2, 2))(x)


x = BatchNormalization()(x)
x = Conv2D(192, (3, 3), activation='relu', padding='same')(x)
x = BatchNormalization()(x)
x = Conv2D(128, (3, 3), activation='relu', padding='same')(x)
x = UpSampling2D((2, 2))(x)

x = BatchNormalization()(x)
x = Conv2D(64, (3, 3), activation='relu', padding='same')(x)
x = BatchNormalization()(x)
x = Conv2D(32, (3, 3), activation='relu', padding='same')(x)
x = UpSampling2D((2, 2))(x)

decoded = Conv2D(1, (3, 3), padding='same')(x)

#autoencoder = Model(inputs=[input_img, shape_input], outputs=decoded)
autoencoder = Model(inputs=input_img, outputs=decoded)
autoencoder = multi_gpu_model(autoencoder, gpus=4)
autoencoder.compile(optimizer='adam', loss='mean_squared_error')


# In[9]:


get_train_generator = lambda: inputs(K.get_session(), '../../data/nd-iris-train-*.tfrecords', 400, 50)
get_val_generator = lambda: inputs(K.get_session(), '../../data/nd-iris-val-*.tfrecords', 400, 50)


class PlotVisdom(Callback):
    def on_train_begin(self, logs={}):

        self.vis = visdom.Visdom()
        startup_sec = 1
        while not self.vis.check_connection()\
                and startup_sec > 0:
            time.sleep(0.1)
            startup_sec -= 0.1

        assert self.vis.check_connection(),\
            'No connection could be formed quickly'

        self.train_generator = get_train_generator()
        self.val_generator = get_val_generator()

    def plot_figures(self, generator, epoch, logs):
        images_to_plot = []
        for image, _ in generator:
            decoded = autoencoder.predict(image)

            for row in range(8):

                images_to_plot.append(image[row].reshape(1, 64, 512))
                images_to_plot.append(decoded[row].reshape(1, 64, 512))
            break
        title = 'Epoch: {}'.format(epoch)

        caption = 'Training Loss: {}, Validation Loss: {}'.format(
            logs.get('loss'), logs.get('val_loss'))

        self.vis.images(images_to_plot, opts=dict(
            nrow=8, title=title, caption=caption))

    def on_epoch_end(self, epoch, logs={}):
        self.plot_figures(self.train_generator, epoch, logs)
        self.plot_figures(self.val_generator, epoch, logs)

# In[ ]:


autoencoder.fit_generator(generator=get_train_generator(),
                epochs=25,
                steps_per_epoch=265, # batch size 400
                validation_data=get_val_generator(),
                validation_steps=190,
                workers = 0,
                use_multiprocessing=True,
                callbacks=[TensorBoard(log_dir='../iris_ae/deep_iris_net_3'),
			   ModelCheckpoint("deep_iris_net_3.{epoch:02d}-{val_loss:.2f}.hdf5", save_weights_only=True),
               PlotVisdom()])
