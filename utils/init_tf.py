import os

import numpy as np
from PIL import Image
from six.moves import cPickle


class LoadedModel:
    def __init__(self, session, graph, model, chars, vocab):
        """
        Initialise the model loaded in this file for future use.
        Intended for use with init_tf unless you know what you are doing

        Args:
            session (tensorflow.Session): The session used to load the model
            graph (tensorflow.Graph): The graph used to load the model
            model (char_rnn.model.Model): The model that was loaded
            chars: Unpickled stuff
            vocab: Unpickled stuff
        """
        self._sess = session
        self._graph = graph
        self._model = model
        self._chars = chars
        self._vocab = vocab

    @property
    def sess(self):
        return self._sess

    @property
    def model(self):
        return self._model

    @property
    def chars(self):
        return self._chars

    @property
    def vocab(self):
        return self._vocab

    @property
    def graph(self):
        return self._graph

    def sample(self, prime=None, n=100, sample=1):
        """
        Sample text. The last step of sample.py in the original char-rnn

        Args:
            prime (str): Prime text
            n (int): Amount of characters to sample
            sample (int):
                0 to use max at each timestep, 1 to sample at
                each timestep, 2 to sample on spaces

        Returns:
            str: Text that was generated as utf-8
        """
        if not prime:
            prime = self.chars[0]

        with self.graph.as_default():
            return self.model.sample(self.sess, self.chars,
                                         self.vocab,
                                         n, prime, sample)


class PokeModel:
    def __init__(self, save_dir):
        import tensorflow as tf

        with open(os.path.join(save_dir, 'config.cpkl'), 'rb') as f:
            args = cPickle.load(f)

        self.image_size = args.image_size
        self.num_channels = 3

        self._sess = tf.Session()
        path = tf.train.latest_checkpoint(save_dir)
        model_nro = path.split('-')[-1]

        saver = tf.train.import_meta_graph(os.path.join(save_dir, f'model.ckpt-{model_nro}.meta'))
        # Step-2: Now let's load the weights saved using the restore method.
        saver.restore(self.sess, path)

        # Accessing the default graph which we have restored
        self._graph = tf.get_default_graph()

        # Now, let's get hold of the op that we can be processed to get the output.
        # In the original network y_pred is the tensor that is the prediction of the network
        self._y_pred = self.graph.get_tensor_by_name("y_pred:0")

        # Let's feed the images to the input placeholders
        self._x = self.graph.get_tensor_by_name("x:0")
        self._y_true = self.graph.get_tensor_by_name("y_true:0")

        with open(os.path.join(save_dir, 'labels.cpkl'), 'rb') as f:
            labels = cPickle.load(f)

        self._y_test_images = np.zeros((1, len(labels)))
        self._labels = labels

    @property
    def sess(self):
        return self._sess

    @property
    def graph(self):
        return self._graph

    def sample(self, image_array):
        feed_dict_testing = {self._x: image_array, self._y_true: self._y_test_images}
        result = self.sess.run(self._y_pred, feed_dict=feed_dict_testing)
        # result is of this format [P1 P2 P3 P4 ... Pn]
        return self._labels[np.argmax(result)], max(result[0])

    def process_image(self, im: Image.Image):
        images = []
        bg = Image.new(im.mode, im.size, 'black')
        bg.paste(im)
        bg = bg.resize((self.image_size, self.image_size), Image.LINEAR)
        image = np.array(bg)[:, :, :3]  # Leave out alpha channel if it exists
        images.append(image)
        images = np.array(images, dtype=np.float32)
        images = np.multiply(images, 1.0 / 255.0)
        # The input to the network is of shape [None image_size image_size num_channels]. Hence we reshape.
        return images.reshape(1, self.image_size, self.image_size, self.num_channels)


def init_poke_tf():
    return PokeModel(os.path.join(os.getcwd(), 'data', 'pokemodel'))


def init_tf():
    import tensorflow as tf
    from char_rnn.model import Model

    # Models should be in data/models
    save_dir = os.path.join(os.getcwd(), 'data', 'models')

    with open(os.path.join(save_dir, 'config.pkl'), 'rb') as f:
        saved_args = cPickle.load(f)
    with open(os.path.join(save_dir, 'chars_vocab.pkl'), 'rb') as f:
        chars, vocab = cPickle.load(f)

    graph = tf.Graph()
    with graph.as_default():
        model = Model(saved_args, training=False)
        sess = tf.Session()
        with sess.as_default() as sess:
            tf.global_variables_initializer().run()
            saver = tf.train.Saver(tf.global_variables())
            ckpt = tf.train.get_checkpoint_state(save_dir)

            if ckpt and ckpt.model_checkpoint_path:
                saver.restore(sess, ckpt.model_checkpoint_path)

    return LoadedModel(sess, graph, model, chars, vocab)
