import React from "react";
import "../App.css";

import Column from "react-bootstrap/Col";
import Card from "react-bootstrap/Card";
import Button from "react-bootstrap/Button";

const Post = ({ data }) => (
  <Column xs={12} lg={6} xl={4} className="mb-4">
    <Card>
      <h2 className="tit">{data.title}</h2>
      <ul>
        {data.summary.map((item, index) => <li key={index}>{item}</li>)}
      </ul>
      <Button href={data.link} className="button-tit">Quero saber mais</Button>
    </Card>
  </Column>
);

export default Post;
