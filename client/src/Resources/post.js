import React from "react";
import "../App.css";

import Column from "react-bootstrap/Col";
import Card from "react-bootstrap/Card";
import Button from "react-bootstrap/Button";

const Post = ({ data }) => (
  <Card>
    <h2 className="tit">{data.title}</h2>
    <ul>
      {data.summary.map((item, index) => <li key={index}>{item}</li>)}
    </ul>
    <Button href={data.link} className="button-tit">Quero saber mais</Button>
  </Card>
);

export default Post;
