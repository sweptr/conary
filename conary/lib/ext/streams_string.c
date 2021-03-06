/*
 * Copyright (c) SAS Institute Inc.
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *     http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */


#include <Python.h>
#include <netinet/in.h>

#include "pycompat.h"
#include "streams.h"

/* debugging aid */
#if defined(__i386__) || defined(__x86_64__)
# define breakpoint do {__asm__ __volatile__ ("int $03");} while (0)
#endif

/* ------------------------------------- */
/* Object definitions                    */

typedef struct {
    PyObject_HEAD
    PyObject * s;
} StringStreamObject;

/* ------------------------------------- */
/* StringStream Implementation          */

static PyObject * StringStream_Call(PyObject * self, PyObject * args,
                                    PyObject * kwargs) {
    StringStreamObject * o = (void *) self;
    static char * kwlist[] = { NULL };

    if (!PyArg_ParseTupleAndKeywords(args, kwargs, "", kwlist))
        return NULL;

    Py_INCREF(o->s);
    return o->s;
}

static int StringStream_Cmp(PyObject * self, PyObject * other) {
    StringStreamObject * s = (void *) self;
    StringStreamObject * o = (void *) other;
    int len_s, len_o, cmpLen, rc;

    if (Py_TYPE(s) != Py_TYPE(o)) {
        PyErr_SetString(PyExc_TypeError, "invalid type");
        return -1;
    }

    if ((s->s == Py_None) && (o->s == Py_None))
	return 0;
    else if (s->s == Py_None)
	return -1;
    else if (o->s == Py_None)
	return 1;

    len_s = PYBYTES_GET_SIZE(s->s);
    len_o = PYBYTES_GET_SIZE(o->s);
    cmpLen = len_s < len_o ? len_s : len_o;

    rc = memcmp(PYBYTES_AS_STRING(s->s), PYBYTES_AS_STRING(o->s), cmpLen);
    /* clamp the value returned from memcmp to -1 or 1 as memcmp() can
       return any value */
    if (rc > 0)
	return 1;
    else if (rc < 0)
	return -1;

    if (len_s < len_o)
	return -1;
    else if (len_s == len_o)
	return 0;
    
    return 1;
}

static void StringStream_Dealloc(PyObject * self) {
    Py_XDECREF(((StringStreamObject *) self)->s);
    Py_TYPE(self)->tp_free(self);
}

static PyObject * StringStream_Diff(StringStreamObject * self, 
				    PyObject * args) {
    StringStreamObject * them;
    int rc;

    if (!PyArg_ParseTuple(args, "O!", Py_TYPE(self), &them))
        return NULL;

    if ((PyObject *) them == Py_None) {
	Py_INCREF(Py_None);
	return Py_None;
    } else if (Py_TYPE(them) != Py_TYPE(self)) {
        PyErr_SetString(PyExc_TypeError, "invalid type");
        return NULL;
    }

    rc = StringStream_Cmp((PyObject *) self, (PyObject *) them);
    if (rc == -1 && PyErr_Occurred()) {
	return NULL;
    } else if (!rc) { 
	Py_INCREF(Py_None);
	return Py_None;
    }

    Py_INCREF(self->s);
    return self->s;
}

static PyObject * StringStream_Eq(PyObject * self, PyObject * args,
                                  PyObject * kwargs) {
    static char * kwlist[] = { "other", "skipSet", NULL };
    PyObject * other;
    int cmp;
    PyObject * rc, * skipSet = NULL;

    if (!PyArg_ParseTupleAndKeywords(args, kwargs, "O!|O", kwlist,
                Py_TYPE(self), &other, &skipSet))
        return NULL;

    /* ignore skipSet */
    cmp = StringStream_Cmp(self, other);
    if (!cmp)
	rc = Py_True;
    else
	rc = Py_False;
    
    Py_INCREF(rc);
    return rc;
}
static PyObject * StringStream_Freeze(StringStreamObject * self, 
                                      PyObject * args,
                                      PyObject * kwargs) {
    PyObject * skipSet = NULL;
    static char * kwlist[] = { "skipSet", NULL };

    if (!PyArg_ParseTupleAndKeywords(args, kwargs, "|O", kwlist, &skipSet))
        return NULL;

    Py_INCREF(self->s);
    return self->s;
}

static long StringStream_Hash(PyObject * self) {
    StringStreamObject * o = (void *) self;
    return Py_TYPE(o->s)->tp_hash(o->s);
}

static int StringStream_Init(PyObject * self, PyObject * args,
                             PyObject * kwargs) {
    StringStreamObject * o = (void *) self;
    PyObject * initObj = NULL;
    static char * kwlist[] = { "frozen", NULL };

    if (!PyArg_ParseTupleAndKeywords(args, kwargs, "|O", kwlist, 
				     &initObj)) {
        return -1;
    }

    if (initObj) {
	if (initObj != Py_None && !PYBYTES_Check(initObj)) {
	    PyErr_SetString(PyExc_TypeError, "frozen value must be "
			    "None or a string");
	    return -1;
	}
	    
	o->s = initObj;
	Py_INCREF(o->s);
    } else {
	o->s = PYBYTES_FromString("");
    }

    return 0;
}

static PyObject * StringStream_Set(StringStreamObject * self, 
				   PyObject * args) {
    PyObject * o, * newval;

    if (!PyArg_ParseTuple(args, "O", &o))
        return NULL;

    if (o == Py_None || PYBYTES_CheckExact(o)) {
	Py_INCREF(o);
	newval = o;
    } else if (PyUnicode_CheckExact(o)) {
	newval = PyUnicode_AsUTF8String(o);
    } else {
        PyErr_SetString(PyExc_TypeError, "invalid type for set");
	return NULL;
    }

    Py_DECREF(self->s);
    self->s = newval;

    Py_INCREF(Py_None);
    return Py_None;
}

static PyObject * StringStream_Thaw(StringStreamObject * self, 
				    PyObject * args) {
    PyObject * o;

    if (!PyArg_ParseTuple(args, "O!", &PYBYTES_Type, &o))
        return NULL;

    Py_INCREF(o);
    Py_DECREF(self->s);
    self->s = o;

    Py_INCREF(Py_None);
    return Py_None;
}

static PyObject * StringStream_Twm(StringStreamObject * self, PyObject * args) {
    char * diff;
    int diffLen;
    StringStreamObject * other;

    /* string streams don't implement a true diff.  A merge is a wholesale
       replacement of the value, as long we don't conflict with the other
       object that's participating in the twm.
    */
    if (!PyArg_ParseTuple(args, "s#O", &diff, &diffLen, &other,
                          Py_TYPE(self)))
        return NULL;

    /* if we are the same as the other object, we can reset our value
       to what is coming in from the diff */
    if (!StringStream_Cmp((PyObject *) self, (PyObject *) other)) {
	Py_DECREF(self->s);
	self->s = PYBYTES_FromStringAndSize(diff, diffLen);
	Py_INCREF(Py_False);
	return Py_False;
    }

    /* otherwise, the only way that there is no conflict is if we are
       already set to the value that is contained in the diff */
    if (self->s == Py_None || (PYBYTES_GET_SIZE(self->s) != diffLen) ||
	memcmp(PYBYTES_AS_STRING(self->s), diff, diffLen)) {
	/* conflict */
	Py_INCREF(Py_True);
	return Py_True;
    }
    /* we're already set to the value of the diff, no conflict */
    Py_INCREF(Py_False);
    return Py_False;
}

/* ------------------------------------- */
/* Type and method definition            */

static PyMethodDef StringStreamMethods[] = {
    { "diff", (PyCFunction) StringStream_Diff, METH_VARARGS,
      "Find the difference between two streams." },
    { "__eq__", (PyCFunction) StringStream_Eq, METH_VARARGS | METH_KEYWORDS, 
      NULL },
    { "freeze", (PyCFunction) StringStream_Freeze, 
      METH_VARARGS | METH_KEYWORDS,
      "Freeze a string stream." },
    { "set", (PyCFunction) StringStream_Set, METH_VARARGS,
      "Set the value of the string stream." },
    { "thaw", (PyCFunction) StringStream_Thaw, METH_VARARGS,
      "Thaw a string stream." },
    { "twm", (PyCFunction) StringStream_Twm, METH_VARARGS,
      "Perform three way merge." },
    {NULL}  /* Sentinel */
};

PyTypeObject StringStreamType = {
    PyVarObject_HEAD_INIT(NULL, 0)
    "cstreams.StringStream",        /*tp_name*/
    sizeof(StringStreamObject),     /*tp_basicsize*/
    0,                              /*tp_itemsize*/
    StringStream_Dealloc,           /*tp_dealloc*/
    0,                              /*tp_print*/
    0,                              /*tp_getattr*/
    0,                              /*tp_setattr*/
    StringStream_Cmp,		    /*tp_compare*/
    0,                              /*tp_repr*/
    0,                              /*tp_as_number*/
    0,                              /*tp_as_sequence*/
    0,                              /*tp_as_mapping*/
    StringStream_Hash,              /*tp_hash */
    StringStream_Call,		    /*tp_call*/
    0,                              /*tp_str*/
    0,                              /*tp_getattro*/
    0,                              /*tp_setattro*/
    0,                              /*tp_as_buffer*/
    Py_TPFLAGS_DEFAULT | Py_TPFLAGS_BASETYPE,             /*tp_flags*/
    NULL,                           /* tp_doc */
    0,                              /* tp_traverse */
    0,                              /* tp_clear */
    0,                              /* tp_richcompare */
    0,                              /* tp_weaklistoffset */
    0,                              /* tp_iter */
    0,                              /* tp_iternext */
    StringStreamMethods,            /* tp_methods */
    0,                              /* tp_members */
    0,                              /* tp_getset */
    0,                              /* tp_base */
    0,                              /* tp_dict */
    0,                              /* tp_descr_get */
    0,                              /* tp_descr_set */
    0,                              /* tp_dictoffset */
    StringStream_Init,		    /* tp_init */
};

void stringstreaminit(PyObject * m) {
    allStreams[STRING_STREAM].pyType  = StringStreamType;
}

/* vim: set sts=4 sw=4 expandtab : */
