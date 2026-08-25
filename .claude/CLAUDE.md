When talking about rust code, only raw `panic!` and `unwrap` calls should be
treated as potential panic points. Other things that panic like `todo!` and
`unreachable!` express different ideas and the fact that they panic is
incidental. If you encounter a `todo!`, first evaluate whether it really should
be done at the current stage of work. If there is more pressing work to do,
ignore it completely. If it is the right time to implement the `todo!` block,
talk about it in terms of work that needs to be done, not in terms of a
potential panic.
