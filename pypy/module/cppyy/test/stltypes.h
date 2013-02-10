#include <list>
#include <map>
#include <string>
#include <vector>

//- basic example class
class just_a_class {
public:
    int m_i;
};

#define STLTYPE_INSTANTIATION(STLTYPE, TTYPE, N)                             \
   std::STLTYPE<TTYPE > STLTYPE##_##N;                                       \
   std::STLTYPE<TTYPE >::iterator STLTYPE##_##N##_i;                         \
   std::STLTYPE<TTYPE >::const_iterator STLTYPE##_##N##_ci

//- instantiations of used STL types
namespace {

    struct _CppyyVectorInstances {

        STLTYPE_INSTANTIATION(vector, int,          1);
        STLTYPE_INSTANTIATION(vector, float,        2);
        STLTYPE_INSTANTIATION(vector, double,       3);
        STLTYPE_INSTANTIATION(vector, just_a_class, 4);

    };

    struct _CppyyListInstances {

        STLTYPE_INSTANTIATION(list, int,          1);
        STLTYPE_INSTANTIATION(list, float,        2);
        STLTYPE_INSTANTIATION(list, double,       3);

    };

} // unnamed namespace

#define STLTYPES_EXPLICIT_INSTANTIATION_DECL_COMPS(STLTYPE, TTYPE)           \
namespace __gnu_cxx {                                                        \
extern template bool operator==(const std::STLTYPE< TTYPE >::iterator&,      \
                         const std::STLTYPE< TTYPE >::iterator&);            \
extern template bool operator!=(const std::STLTYPE< TTYPE >::iterator&,      \
                         const std::STLTYPE< TTYPE >::iterator&);            \
}

// comps for int only to allow testing: normal use of vector is looping over a
// range-checked version of __getitem__
STLTYPES_EXPLICIT_INSTANTIATION_DECL_COMPS(vector, int)


//- class with lots of std::string handling
class stringy_class {
public:
   stringy_class(const char* s);

   std::string get_string1();
   void get_string2(std::string& s);

   void set_string1(const std::string& s);
   void set_string2(std::string s);

   std::string m_string;
};
