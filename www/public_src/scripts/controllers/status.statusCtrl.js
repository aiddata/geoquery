angular.module('aiddataDET')
.controller('StatusCtrl', function($stateParams, $scope, request, datasets, language) {
  $scope.id = $stateParams.id;
  $scope.request = request;
  $scope.language = [];

  $scope.getDataset = function (query) {
    var name = query.dataset || query.name;

    return _.find(datasets, {name : name });
  };

  $scope.$on('$viewContentLoaded', function() {
    request.status = _.chain(request.stage)
      .filter('time')
      .last()
      .get('name')
      .value();

    $scope.language = language.status[request.status];
  });

  $scope.pastTense = function(word) {
    return word === 'submit' ? 'submitted' :
      word === 'prep' ? 'prepped' :
      word === 'process' ? 'processed' : '';
  };
});
