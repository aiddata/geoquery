angular.module('aiddataDET')
.controller('OptionsCtrl', function($scope, $rootScope, $log) {
  $scope.dataset = {};

  $scope.options = [
    {
      name: "Extract Options",
      type: "checkbox",
      loc: "options.extract_types",
      data: []
    },
    {
      name: "Resources",
      type: "checkbox",
      loc: "resources",
      data: []
    },
    {
      name: "Metadata",
      type: "paragraph"
    }
  ];

  $rootScope.$on('dataset:selected', function(e, data) {
    $scope.dataset = data;

    if (data.type !== 'raster') { return; }
    _.each($scope.options, function(option) {
      if (option.loc) {
        option.data = _.chain($scope.dataset)
          .get(option.loc)
          .map(function(choice) {
            return _.isString(choice) ? { name: choice } : choice;
          })
          .value();
      }
    });
  });

});
