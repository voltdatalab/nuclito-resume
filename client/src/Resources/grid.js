import React from "react";
import "../App.css";
import Post from "./post";

import Container from "react-bootstrap/Container";
import Row from "react-bootstrap/Row";

const Grid = ({ posts }) => (
  <Container>
    <Row className="g-3">
      {posts.map((post) => <Post data={post} />)}
    </Row>
  </Container>
);

export default Grid;
